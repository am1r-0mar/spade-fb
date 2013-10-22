import sys
import os
import logging
import pdb
import code

from java.io import BufferedWriter, OutputStreamWriter, FileOutputStream

import anyjson
import fbconsole

from os import path

from utils import ignore_exception, filter_dict

REPL_DEBUG = True
SOCKET_PATH = "/tmp/spade"
CURDIR = path.split(path.abspath(__file__))[0]
DUMPDIR = path.abspath( path.join(CURDIR, "../", "userdata/") )
CREATE_NODES_FOR_NONFRIENDS = False
if not os.path.exists(DUMPDIR):
    os.makedirs(DUMPDIR)

logging.basicConfig(level=logging.INFO)


class FBDownloader:
	""" 
	Downloads data from Facebook and saves it temporarily
	"""
	
	def __init__(self, dump_path):

		fbconsole.AUTH_SCOPE = ['user_friends', 'read_stream', 'friends_actions.news', 'friends_activities', 'friends_photos']
		fbconsole.authenticate()

		self.fb = fbconsole
		self.dump_path = dump_path
		self.logger = logging.getLogger(self.__class__.__name__)

	def download(self):
		userdata, userfriends, usernewsfeed = self.get_user_data()

		self._save_data("me_data", userdata)
		self._save_data("me_friends", userfriends)
		self._save_data("me_newsfeed", usernewsfeed)
	
		
		for friend in userfriends:
			friend_id = friend['id']
			try:
				friend_info, friend_friends, friend_feed = self.get_person_data(friend_id)
				self._save_data("%s_info" % friend_id, friend_info)
				self._save_data("%s_friends" % friend_id, friend_friends)
				self._save_data("%s_feed" % friend_id, friend_feed)
			except Exception, e:
				logger.error("Error while fetching %s (%s)'s' data: %s" % (friend['name'], friend['id'], e.message))



	def get_user_data(self):
		"""
		Gets userinfo, friends and home newsfeed
		"""
		try:
			fb = self.fb 
			userinfo = fb.get("/me/")

			res = fb.get("/me/friends/")
			friends = res['data']

			newsfeed = fb.get("/me/home/")

			return (userinfo, friends, newsfeed)
		except Exception, e:			
			pdb.set_trace()
			raise e


		
	def get_person_data(self, fuid):
		"""
		Gets data of a person,
		returns userinfo and newsfeed
		"""
		try:
			fb = self.fb
			userinfo = fb.get("/%s" % fuid)
			friends = [] # fb.get("/%s/friends" % fuid )
			feed = fb.get("/%s/feed" % fuid)['data']
			return userinfo, friends, feed
		except Exception, e:
			if REPL_DEBUG: 
				pdb.set_trace()
			raise e


	def _save_data(self, filename, jsondata):
		"""
		Dumps json data in a file
		"""
		if not filename.endswith(".json"):
			filename += ".json"
		if not filename.startswith(self.dump_path):
			filename = path.join(self.dump_path, filename)
		if type(jsondata) not in [str, unicode]:
			jsondata = anyjson.serialize(jsondata)
		print ("File: %s" % filename)
		f = open(filename, "w")
		f.write(jsondata)
		f.close()

class DSLSerializable:
	""" Used to represent a Node or Edge and serialize it for SPADE DSL Reporter"""
	def __init__(self, stype, s_id=None):
		self.attrs = {}
		self.stype = stype
		self.s_id = s_id

	def serialize(self):
		""" Returns a serialized verion of the data """
		esc = self._escape_data
		attrdata = " ".join( "%s:%s" % (esc(k), esc(unicode(v))) for k,v in self.attrs.iteritems() if k not in ['id'])
		if self.s_id:
			return "type:%s id:%s %s\n" % (esc(self.stype), esc(self.s_id), attrdata)
		else:
			return "type:%s %s\n" % (esc(self.stype), attrdata)


	def add_attr(self, key, val):
		remap = {'type': 'fbtype', 'id': 'fbid', 'actions': 'fbactions'}
		if not remap.has_key(key):		
			self.attrs[key] = val
		else:
			self.attrs[ remap[key] ] = val

	def add_attrs(self, attrs):
		for k,v in attrs.iteritems():
			self.add_attr(k, v)

	def _escape_data(self, string):
		"""
		Escapes the data for sending to SPADE 
		"""
		try:
			if type(string) not in [str, unicode]:
				string = unicode(string)
			return string.replace(" ", r"\ ").replace('"', r'\"').replace("'", r"\'").replace("\n", r"\n")
		except Exception, e:
			if REPL_DEBUG:
				import code
				code.interact(local=locals())
			raise e

class SPADEFeeder:


	def __init__(self, dump_path, dsl_pipe):
		self.dump_path = dump_path
		if not os.path.exists(dsl_pipe):
			raise Exception("""
				The path to pipe for DSL reporter %s does not exists. 
				Make sure SPADE is running and DSL reporter has been setup. 
				For more infromation, take a look at http://code.google.com/p/data-provenance/wiki/Pipe""")
		self.pipe = BufferedWriter( OutputStreamWriter(FileOutputStream( dsl_pipe ) ))
		self.logger = logging.getLogger(self.__class__.__name__)


		self.user_data = self._read_json_data("me_data")
		self.user_newsfeed = self._read_json_data("me_newsfeed")

		self.friends = dict()
		self.created_user_nodes = set()

		for f in self._read_json_data("me_friends"):
			fuid = f['id']
			try:
				self.friends[fuid] = self._read_json_data("%s_info" % fuid)
			except IOError, e:
				logger.info("Skipping data for friend %s; unable to read data" % f['name'])
				self.friends[fuid] = f
		self.friends[self.user_data['id']] = self.user_data

	def create_person_node_if_not_exists(self, user_id, userdata):
		""" Creates a person node if it doesn't already exists """
		try:
			if user_id in self.created_user_nodes:
				return False
			person_node = DSLSerializable("Process", user_id)
			person_node.add_attrs(userdata)
			self.write_dsl(person_node)
			self.created_user_nodes.add(user_id)
			return True
		except Exception, e:
			logger.exception("Unable to create person node")
			if REPL_DEBUG:
				import code
				code.interact(local=locals())
			return False

	def write_dsl(self, serializable):
		""" Takes a DSLSeralizable object and writes it to SPADE """
		data = serializable.serialize()
		logger.info(data)
		self.pipe.write(data)

	def feed(self):
		"""
		Sends the read data to SPADE
		"""

		# Create nodes for all users
		for fuid, userdata in self.friends.iteritems():
			try:
				self.create_person_node_if_not_exists(fuid, userdata)
			except Exception, e:
				if REPL_DEBUG:
					import code
					code.interact(local=locals())

		# For each person
		for fuid, userdata in self.friends.iteritems():
			try:
				userfeed = self._read_json_data("%s_feed" % fuid)
				logger.info("Now processing feed of user %s" % fuid)

				# For each activity
				for activity in userfeed:

					try:
						# Create Node
						node = DSLSerializable("Artifact", activity['id'])
						node.add_attr("time", activity['created_time'])
						node.add_attrs( filter_dict(activity, ['likes', 'shares', 'from', 'created_time']) )
						self.write_dsl(node)
						if not activity.get("from") or (activity.get("from") and activity.get("from") == fuid):
							# Create edge between owner and created node
							edge = DSLSerializable("WasGeneratedBy")
							edge.add_attr("from", activity['id'])
							edge.add_attr("to", fuid)
							edge.add_attr("context", "timeline")
							self.write_dsl(edge)
						else:
							# Create a WasGeneratedBy edge from the user who posted to the post 
							# and a Read edge from the user on whose timeline was posted to the post
							edge = DSLSerializable("WasGeneratedBy")
							edge.add_attr("from", activity['id'])
							edge.add_attr("to", activity['from'])
							edge.add_attr("context", "timeline_post")
							self.write_dsl(edge)

							edge = DSLSerializable("WasControlledBy")
							edge.add_attr("from", activity['id'])
							edge.add_attr("to", fuid)
							edge.add_attr("context", "timeline_post")
							self.write_dsl(edge)

						# Handle post likes
						if activity.has_key("likes"):
							# TODO: Handle pagination for large number of likes on a post
							for like in activity['likes']['data']:
								if CREATE_NODES_FOR_NONFRIENDS:
									self.create_person_node_if_not_exists(like)
								if CREATE_NODES_FOR_NONFRIENDS or self.friends.has_key(like['id']):
									edge = DSLSerializable("Used")
									edge.add_attr("from", like['id'])
									edge.add_attr("to", activity['id'])
									edge.add_attr("context", "like")
									self.write_dsl(edge)

						# Handle post comments
						if activity.has_key("comments"):
							for comment in activity['comments']['data']:
								commenter = comment['from']
								if CREATE_NODES_FOR_NONFRIENDS:
									self.create_person_node_if_not_exists(commenter['id'], commenter)
								if CREATE_NODES_FOR_NONFRIENDS or self.friends.has_key(like['id']):
									comment_node =  DSLSerializable("Artifact", comment['id'])
									comment_node.add_attrs(comment)
									comment_node.add_attr("type", "comment")
									self.write_dsl(comment_node)

									edge = DSLSerializable("WasDerivedBy")
									edge.add_attr("from", comment['id'])
									edge.add_attr("to", activity['id'])
									self.write_dsl(edge)

									edge = DSLSerializable("WasGeneratedBy")
									edge.add_attr("from", comment['id'])
									edge.add_attr("to", commenter['id'])
									self.write_dsl(edge)



						# TODO: Handle Facebook shares in one collapsed node?

					except Exception, e:
						logger.error(e.message)
						if REPL_DEBUG:
							import code;	code.interact(local=locals())

			except IOError, e:
				logger.info("Unavailable feed details of %s. Skipping ... " % fuid)
			except Exception, e:
				if REPL_DEBUG:
					import code;	code.interact(local=locals())

	def _read_json_data(self, filename):
		if not filename.endswith(".json"):
			filename += ".json"
		if not filename.startswith(self.dump_path):
			filename = path.join(self.dump_path, filename)
		f = open(filename, "r")
		data = f.read()
		f.close()
		return anyjson.deserialize(data)

if __name__ == '__main__':

	logger = logging.getLogger("SPADE-FB")

	if "--fetch" in sys.argv:
		fbsaver = FBDownloader(DUMPDIR)
		fbsaver.download()

	if "--nofeed" not in sys.argv:
		logger.debug("Setting up Feeder for /tmp/spade")
		feeder = SPADEFeeder(DUMPDIR, "/tmp/spade")
		logger.info("Feeder initialized. Now feeding")
		feeder.feed()
		logger.info("Fed data to SPADE!")

	if "--post-introspect" in sys.argv:
		# drop an interactive shell for tinkering around
		logger.info("Dropping to shell for introspection after execution")
		code.interact(local=locals())




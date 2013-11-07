import sys
import os
import logging
import pdb
import code
from time import sleep

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

logging.basicConfig(level=logging.DEBUG)

FB_ACTIVITY_TYPES = "status photo comment link".split()
SPADE_FB_PROCESSES = FB_ACTIVITY_TYPES + "likes timeline friendship".split()

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

class IDMapper:
	""" Creates and maintains numerics SPADE IDs against Facebook's semi-numeric IDs

	Tests

	>>> mapper = IDMapper()
	>>> mapper[None]
	None
	>>> mapper["hello"] 
	0
	>>> mapper["world"]
	1
	>>> mapper[1337]
	2
	>>> mapper["world"]
	1
	>>> mapper[1337]
	2
	>>> mapper[None]
	None
	"""

	def __init__(self):
		self._next_id = 0
		self._mapping = {}

	def __getitem__(self, itemid):
		if itemid is None:
			return None
		if self._mapping.has_key(itemid):
			return self._mapping[itemid]
		else:
			ret = self._mapping[itemid] = self._next_id
			self._next_id += 1
			return ret 

id_mapper = IDMapper()

class DSLSerializable:
	""" Used to represent a Node or Edge and serialize it for SPADE DSL Reporter"""
	def __init__(self, stype, fb_obj_id=None):
		self.attrs = {}
		self.stype = stype
		self.fb_obj_id = fb_obj_id

	def _keyval_serialize(self, k,v):
		global id_mapper
		if k in ['from', 'to', 'id']:
			v = id_mapper[v]
		esc = self._escape_data
		return (esc(k), esc(unicode(v)) )

	def serialize(self):
		""" Returns a serialized verion of the data """
		global id_mapper
		esc = self._escape_data
		
		attrdata = " ".join( "%s:%s" % self._keyval_serialize(k,v) for k,v in self.attrs.iteritems() if k not in ['id'])
		if self.fb_obj_id:
			return "type:%s id:%s %s\n" % (esc(self.stype), id_mapper[self.fb_obj_id], attrdata)
		else:
			return "type:%s %s\n" % (esc(self.stype), attrdata)


	def add_attr(self, key, val):
		remap = {'type': 'fbtype', 'id': 'fbid', 'actions': 'fbactions'}

		if remap.has_key(key):
			key = remap[key]

		self.attrs[ key ] = val

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
		""" 
		Creates a person's Agent node, Status, Likes, Comment, Timeline and Post process nodes
		"""
		try:
			if user_id in self.created_user_nodes:
				return False

			person_node = DSLSerializable("Agent", user_id + ".agent")
			person_node.add_attrs(userdata)
			self.write_dsl(person_node)

			for process in SPADE_FB_PROCESSES:
				node_id = user_id + "." + process;
				node = DSLSerializable("Process", node_id)
				node.add_attr("name", process)
				node.add_attr("fbuid", user_id)
				node.add_attr("fbname", userdata.get("name", "[None]"))
				self.write_dsl(node)
				edge = DSLSerializable("WasControlledBy")
				edge.add_attr("to", user_id + ".agent")
				edge.add_attr("from", node_id)
				self.write_dsl(edge)


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
		me_fbuid = self.user_data['id']
		self.create_person_node_if_not_exists(me_fbuid, self.user_data)

		for fuid, userdata in self.friends.iteritems():
			try:
				self.create_person_node_if_not_exists(fuid, userdata)

				# Friendship edges
				edge = DSLSerializable("WasTriggeredBy")
				edge.add_attr("from", fuid+".friendship")
				edge.add_attr("to", me_fbuid+".friendship")
				self.write_dsl(edge)

				edge = DSLSerializable("WasTriggeredBy")
				edge.add_attr("to", fuid+".friendship")
				edge.add_attr("from", me_fbuid+".friendship")
				self.write_dsl(edge)

			except Exception, e:
				logger.exception("Error while creating user node")
				if REPL_DEBUG:
					import code
					code.interact(local=locals())

		# For each person
		for fuid, userdata in self.friends.iteritems():

			pass
			try:

				# Create friendship edges
				userfeed = self._read_json_data("%s_feed" % fuid)
				logger.info("Now processing feed of user %s" % fuid)

				# For each activity
				for activity in userfeed:

					try:
						# Create Node
						node = DSLSerializable("Artifact", activity['id'])
						node.add_attr("time", activity['created_time'])
						node.add_attrs( filter_dict(activity, ['likes', 'shares', 'to', 'from', 'created_time', 'comments']) )
						self.write_dsl(node)

						if activity.get("from"):
							post_from = activity["from"]["id"]
							self.create_person_node_if_not_exists(activity["from"]["id"], activity["from"])
						else:
							post_from = fuid

						if activity.get("to"):
							post_to = [i["id"] for i in activity["to"]["data"] ]
							for i in activity["to"]["data"]:
								self.create_person_node_if_not_exists(i["id"], i)
						else:
							post_to = [fuid]

						# TODO: Handle shares separately
						if activity.get("type") in FB_ACTIVITY_TYPES:
							activity_type = activity.get("type")
						else:
							default_activity = "status"
							activity_type = activity.get("type", default_activity)
							logger.warn( "Uknown FB Activity type: %s. Resorting to %s" % ( str(activity.get("type")), default_activity) )

						edge = DSLSerializable("WasGeneratedBy")
						edge.add_attr("from", post_from + "." + activity_type)
						edge.add_attr("to", activity['id'])
						self.write_dsl(edge)

						for i in post_to:
							edge = DSLSerializable("Used")
							edge.add_attr("from", i + ".timeline")
							edge.add_attr("to", activity['id'])
							self.write_dsl(edge)

						# Handle post likes
						if activity.has_key("likes"):
							# TODO: Handle pagination for large number of likes on a post
							for like in activity['likes']['data']:
								if CREATE_NODES_FOR_NONFRIENDS:
									self.create_person_node_if_not_exists(like['id'], like)
								if CREATE_NODES_FOR_NONFRIENDS or self.friends.has_key(like['id']):
									edge = DSLSerializable("Used")
									edge.add_attr("from", like['id'] + ".likes")
									edge.add_attr("to", activity['id'])
									self.write_dsl(edge)

						# Handle post comments
						if activity.has_key("comments"):
							for comment in activity['comments']['data']:
								commenter = comment['from']
								if CREATE_NODES_FOR_NONFRIENDS:
									self.create_person_node_if_not_exists(commenter['id'], commenter)
								if CREATE_NODES_FOR_NONFRIENDS or self.friends.has_key(like['id']):
									comment_node =  DSLSerializable("Artifact", comment['id'])
									comment_node.add_attrs( filter_dict(comment, ['from','id', 'to', 'likes']) )
									comment_node.add_attr("type", "comment")
									self.write_dsl(comment_node)

									edge = DSLSerializable("WasGeneratedBy")
									edge.add_attr("from", comment['id'])
									edge.add_attr("to", commenter['id'] + ".process")
									self.write_dsl(comment_node)

									edge = DSLSerializable("WasDerivedFrom")
									edge.add_attr("from", comment['id'])
									edge.add_attr("to", activity['id'])
									self.write_dsl(comment_node)

						# TODO: Handle Facebook shares in one collapsed node?

					except Exception, e:
						logger.error(e.message)
						if REPL_DEBUG:
							import code;	code.interact(local=locals())

			except IOError, e:
				logger.info("Unavailable feed details of %s. Skipping ... " % fuid)
			except Exception, e:
				logger.exception("")
				if REPL_DEBUG:
					import code;	code.interact(local=locals())
			finally:
				try:
					self.pipe.flush()
				except Exception, e:
					pass

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

	if "--test" in sys.argv:
		import doctest
		doctest.testmod()
		sys.exit(0)

	if "--fetch" in sys.argv:
		fbsaver = FBDownloader(DUMPDIR)
		fbsaver.download()

	if "--nofeed" not in sys.argv:
		logger.debug("Setting up Feeder for %s" % SOCKET_PATH)
		feeder = SPADEFeeder(DUMPDIR, SOCKET_PATH)
		logger.info("Feeder initialized. Now feeding")
		feeder.feed()
		logger.info("Fed data to SPADE!")
		sleep(1)

	if "--post-introspect" in sys.argv:
		# drop an interactive shell for tinkering around
		logger.info("Dropping to shell for introspection after execution")
		code.interact(local=locals())




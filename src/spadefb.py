import sys
import os
import logging
import pdb
import code

from java.io import BufferedWriter, OutputStreamWriter, FileOutputStream

import anyjson
import fbconsole

from os import path

from utils import ignore_exception

REPL_DEBUG = False
SOCKET_PATH = "/tmp/spade"
CURDIR = path.split(path.abspath(__file__))[0]
DUMPDIR = path.abspath( path.join(CURDIR, "../", "userdata/") )
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
		if type(jsondata) is not str:
			jsondata = anyjson.serialize(jsondata)
		print ("File: %s" % filename)
		f = open(filename, "w")
		f.write(jsondata)
		f.close()

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
		for f in self._read_json_data("me_friends"):
			fuid = f['id']
			try:
				self.friends[fuid] = self._read_json_data("%s_info" % fuid)
			except IOError, e:
				logger.info("Skipping data for friend %s; unable to read data" % f['name'])
				self.friends[fuid] = f
		self.friends[self.user_data['id']] = self.user_data

	def feed(self):
		"""
		Sends the read data to SPADE
		"""
		esc = self._escape_data

		# Create nodes for all users
		for fuid, userdata in self.friends.iteritems():
			try:
				data = " ".join( esc(k) + ":" + esc(v) for k,v in userdata.iteritems() )
				data = "type:Process id:%s %s\n" % (fuid, data)
				self.pipe.write(data)
			except Exception, e:
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
						data = "type:Artifact id:%s message:%s time:%s\n" % (activity['id'], esc(activity['message']), esc(activity['created_time']))
						self.pipe.write(data)
						# Create edge between owner and created node
						data = "type:WasGeneratedBy from:%s to:%s\n" % (activity['id'], fuid)
						self.pipe.write(data)

						if activity.has_key("likes"):
							for like in activity['likes']['data']:
								if self.friends.has_key(like['id']): # TODO: Create a new entry if we are seeing a new person
									data = "type:Used from:%s to:%s\n" % (fuid, activity['id'])
									self.pipe.write(data)
					except Exception, e:
						if REPL_DEBUG:
							import code;	code.interact(local=locals())
						else:
							logger.error(e.message)

			except IOError, e:
				logger.info("Unavailable feed details of %s. Skipping ... " % fuid)
			except Exception, e:
				if REPL_DEBUG:
					import code;	code.interact(local=locals())

	def _escape_data(self, string):
		"""
		Escapes the data for sending to SPADE 
		"""
		try:
			if type(string) not in [str, unicode]:
				string = str(string)
			return string.replace(" ", r"\ ").replace('"', r'\"').replace("'", r"\'").replace("\n", r"\n")
		except Exception, e:
			import code
			code.interact(local=locals())

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

	if "--post-introspect" in sys.argv or REPL_DEBUG:
		# drop an interactive shell for tinkering around
		logger.info("Dropping to shell for introspection after execution")
		code.interact(local=locals())




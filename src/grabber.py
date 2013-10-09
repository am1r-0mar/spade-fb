import fbconsole


fbconsole.AUTH_SCOPE = ['user_friends', 'friends_actions.news', 'friends_activities', 'friends_photos']
fbconsole.authenticate()


# drop an interactive shell for tinkering around

import code
code.interact(local=locals())

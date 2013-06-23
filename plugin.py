###
# Copyright (c) 2013, Arik Baratz
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import os
import sqlite3
import collections

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.ircmsgs as ircmsgs

meeting_singleton = None

class Meeting(callbacks.Plugin, plugins.ChannelDBHandler):
    """This plugin deals with these entities:
    
    Meetings - the scope of the meeting containing agenda items and motions, and participants.
    Adenda - items on the agenda, splitting the discussion along topica
    Motion - a motion (voted on by the members present in the meeting
    
    list this module to see the different options"""
    def __init__(self, irc):
        global meeting_singleton
        #self.__parent = super(Meeting, self)
        #self.__parent.__init__(irc)
        callbacks.Plugin.__init__(self, irc)
        plugins.ChannelDBHandler.__init__(self)
        
        # collect current meeting IDs
        self._current_meeting = {}
        
        # keep a reference to the singleton so that we can reference it from sub commands
        meeting_singleton = self

    def die(self):
        """so you're going to die"""
        global meeting_singleton
        
        # allow efficient GC by removing the module level reference to the object
        meeting_singleton = None
        plugins.ChannelDBHandler.die(self)
        callbacks.Plugin.die(self)

    def makeDb(self, filename):
        need_to_create = not os.path.exists(filename)
        
        db = sqlite3.connect(filename)
        db.text_factory = str

        if need_to_create:
            cursor = db.cursor()
            cursor.execute("""CREATE TABLE meeting (
                                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  name TEXT,
                                  start_time TIMESTAMP NULL,
                                  end_time TIMESTAMP NULL
                              )""")
            cursor.execute("""CREATE TABLE agenda (
                                  id INTEGER PRIMARY KEY,
                                  meeting_id INTEGER,
                                  item_order INTEGER,
                                  item_text TEXT,
                                  
                                  FOREIGN KEY(meeting_id) REFERENCES meeting(id)
                              )""")
            cursor.execute("""CREATE TABLE motion (
                                  id INTEGER PRIMARY KEY,
                                  meeting_id INTEGER,
                                  item_order INTEGER,
                                  motion_text TEXT,
                                  carries BOOLEAN,
                                  votes_aye INTEGER,
                                  votes_nay INTEGER,
                                  decision_at TIMESTAMP,
                                  
                                  FOREIGN KEY(meeting_id) REFERENCES meeting(id)
                              )""")            
            cursor.execute("""CREATE TABLE currents (
                                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  name TEXT,
                                  value INTEGER
                            )""")
            db.commit()

        return db

    def get_current_meeting_id(self, channel):
        """returns the meeting ID or None if doesn't exist"""
        return self._current_meeting.get(channel, None)

    def prepare(self, irc, msg, args, channel, meet_name):
        """[<channel>] <meeting name>
        
        Initialises a meeting
        """
        
        # get the database
        db = self.getDb(channel)

        # insert the new meeting
        cursor = db.cursor()
        cursor.execute("""INSERT INTO meeting
                          VALUES (NULL, ?, NULL, NULL)""", (meet_name, ))
        meeting_id = cursor.lastrowid
        db.commit()

        self._current_meeting[channel] = meeting_id
                
        irc.reply("Meeting initialised, meeting id %d on channel %s" % (meeting_id, channel))
        
    prepare = wrap(prepare, ['channel', 'text'])

    def start(self, irc, msg, args, channel):
        """[<channel>]
        
        Starts the meeting
        """

        # get the meeting id
        meeting_id = self.get_current_meeting_id(channel)
        if meeting_id is None:
            irc.error("No active meeting on channel %s" % channel)
            return

        # get the database
        db = self.getDb(channel)

        # get the meeting details       
        cursor = db.cursor()
        cursor.execute("""SELECT name
                          FROM meeting
                          WHERE id=?""", (meeting_id, ))

        results = cursor.fetchall()
        if len(results)==0:
            irc.error("This shouldn't happen... current meeting id %d invalid" % meeting_id)
            return
        
        meeting_name = results[0][0]
        
        # mark the meeting as started
        cursor.execute("""UPDATE meeting
                          SET start_time=datetime('now')
                          WHERE id=? """, (meeting_id,))       
        db.commit()
                
        irc.queueMsg(ircmsgs.topic(channel, meeting_name))
        irc.reply("The meeting has started. Meeting topic: %s (meeting id %d)" % (meeting_name, meeting_id))
        
    start = wrap(start, ['channel'])

    def adjourn(self, irc, msg, args, channel):
        """[<channel>]
        
        Adjourns the meeting
        """

        # get the meeting id
        meeting_id = self.get_current_meeting_id(channel)        
        if meeting_id is None:
            irc.error("No active meeting on channel %s" % channel)
            return

        # get the database
        db = self.getDb(channel)

        # get the meeting details       
        cursor = db.cursor()
        cursor.execute("""SELECT name
                          FROM meeting
                          WHERE id=?""", (meeting_id, ))

        results = cursor.fetchall()
        if len(results)==0:
            irc.error("This shouldn't happen... current meeting id %d invalid" % meeting_id)
            return
        
        meeting_name = results[0][0]
        
        # mark the meeting as ended
        cursor.execute("""UPDATE meeting
                          SET end_time=datetime('now')
                          WHERE id=? """, (meeting_id,))       
        db.commit()
                
        irc.queueMsg(ircmsgs.topic(channel, meeting_name))
        irc.reply("The meeting has adjourned. Meeting topic: %s (meeting id %d)" % (meeting_name, meeting_id))
        
    adjourn = wrap(adjourn, ['channel'])

    def switchid(self, irc, msg, args, channel, meeting_id):
        """[<channel>] <meeting_id>
        
        Switch to a meeting with a given ID
        """

        # get the database
        db = self.getDb(channel)

        # get the meeting details       
        cursor = db.cursor()
        cursor.execute("""SELECT name
                          FROM meeting
                          WHERE id=?""", (meeting_id, ))

        results = cursor.fetchall()
        if len(results)==0:
            irc.error("Cannot switch - meeting id %d doesn't belong in channel %s or is invalid" % (meeting_id, channel))
            return
        
        meeting_name = results[0][0]

        # switch
        self._current_meeting[channel] = meeting_id
        
        irc.reply("Switched to meeting id %d, meeting name %s" % (meeting_id, meeting_name))
        
    switchid = wrap(switchid, ['channel', 'positiveInt'])

    def status(self, irc, msg, args, channel):
        """[<channel>]
        
        Reply with the status of the current meeting
        """

        # get the meeting id
        meeting_id = self.get_current_meeting_id(channel)
        if meeting_id is None:
            irc.reply("Channel %s does not have a current meeting" % channel)
            return
        
        # get the database
        db = self.getDb(channel)

        # get the meeting details       
        cursor = db.cursor()
        cursor.execute("""SELECT name, start_time, end_time
                          FROM meeting
                          WHERE id=?""", (meeting_id, ))

        results = cursor.fetchall()
        if len(results)==0:
            irc.error("Current meeting for channel %s is %d, but it seems to be invalid." % (channel, meeting_id))
            return
        
        meeting_name, start_time, end_time = results[0]

        irc.reply("Current meeting for channel %s is %s (id %d)" % (channel, meeting_name, meeting_id))
        if end_time:
            irc.reply("The meeting has adjourned")
        elif start_time:
            irc.reply("The meeting is currently in progress")
        else:
            irc.reply("The meeting has not started yet")
            
        irc.reply("Working with object %s" % repr(self))
        
    status = wrap(status, ['channel'])

    class agenda(callbacks.Commands):
        
        def get_max_item_order(self, db, meeting_id):
            """return the latest agenda item order, or zero if no items"""
            
            cursor = db.cursor()            
            cursor.execute("""SELECT max(item_order)
                              FROM agenda
                              WHERE meeting_id=?""", (meeting_id, ))
                       
            results = cursor.fetchall()
            if not results[0][0]: # no agenda item yet
                return 0

            return results[0][0]
        
        def add(self, irc, msg, args, channel, agenda_text):
            """[<channel>] agenda text...
            
            Add an agenda item to the end of the agenda
            """

            # get the current meeting ID
            meeting_id = meeting_singleton.get_current_meeting_id(channel)
            if meeting_id is None:
                irc.error("There is no current meeting in channel %s" % channel)
                return

            # get the database
            db = meeting_singleton.getDb(channel)
            
            # figure out the highest agenda item id used so far
            agenda_item_order = self.get_max_item_order(db, meeting_id) + 1
            
            # insert the new item
            cursor = db.cursor()
            cursor.execute("""INSERT INTO agenda
                              VALUES (NULL, ?, ?, ?)""",
                              (meeting_id, agenda_item_order, agenda_text))
            db.commit()
            
            irc.reply("Agenda item %d added to the current meeting" % agenda_item_order)
                
        add = wrap(add, ['channel', 'text'])

        def list(self, irc, msg, args, channel):
            """[<channel>]
            
            List the agenda for the current meeting in the channel
            """
            # get the current meeting ID
            meeting_id = meeting_singleton.get_current_meeting_id(channel)
            if meeting_id is None:
                irc.error("There is no current meeting in channel %s" % channel)
                return

            # get the database
            db = meeting_singleton.getDb(channel)

            # get the agenda items
            cursor = db.cursor()            
            cursor.execute("""SELECT item_order, item_text
                              FROM agenda
                              WHERE meeting_id=?
                              ORDER BY item_order ASC""", (meeting_id, ))
                       
            results = cursor.fetchall()

            if len(results)==0:
                irc.reply("The current meeting does not have an agenda yet")
                return
            
            for item_order, item_text in results:
                irc.reply("Item %d: %s" % (item_order, item_text))
            
        list = wrap(list, ['channel'])

        def delete(self, irc, msg, args, channel, item_id):
            """[<channel>] <item_id>
            
            Delete an item from the agenda, renumbering following items
            """
            
            # get the current meeting ID
            meeting_id = meeting_singleton.get_current_meeting_id(channel)
            if meeting_id is None:
                irc.error("There is no current meeting in channel %s" % channel)
                return

            # get the database
            db = meeting_singleton.getDb(channel)

            # see how many we have now
            total_items = self.get_max_item_order(db, meeting_id)
            
            # check parameter
            if item_id > total_items:
                irc.error("Cannot delete non-existent item %d" % item_id)
                return
                
            # do the delete
            cursor = db.cursor()
            cursor.execute("""DELETE FROM agenda
                              WHERE meeting_id=?
                              AND item_order=?""", (meeting_id, item_id))
            
            # renumber the rest of the items
            for item in range(item_id+1, total_items+1):
                cursor.execute("""UPDATE agenda
                                  SET item_order=?
                                  WHERE meeting_id=?
                                  AND item_order=?""", (item-1, meeting_id, item))
                
            db.commit()
            
            irc.reply("Agenda item %d has been deleted" % item_id)
            
        delete = wrap(delete, ['channel', 'positiveInt'])

    class motion(callbacks.Commands):

        def get_max_item_order(self, db, meeting_id):
            """return the latest motion item order, or zero if no items"""
            
            cursor = db.cursor()            
            cursor.execute("""SELECT max(item_order)
                              FROM motion
                              WHERE meeting_id=?""", (meeting_id, ))
                       
            results = cursor.fetchall()
            if not results[0][0]: # no motion item yet
                return 0

            return results[0][0]
        
        def add(self, irc, msg, args, channel, motion_text):
            """[<channel>] motion text...
            
            Add a motion to the end of the agenda
            """

            # get the current meeting ID
            meeting_id = meeting_singleton.get_current_meeting_id(channel)
            if meeting_id is None:
                irc.error("There is no current meeting in channel %s" % channel)
                return

            # get the database
            db = meeting_singleton.getDb(channel)
            
            # figure out the highest motion item id used so far
            motion_item_order = self.get_max_item_order(db, meeting_id) + 1
            
            # insert the new item
            cursor = db.cursor()
            cursor.execute("""INSERT INTO motion
                              VALUES (NULL, ?, ?, ?,
                              NULL, NULL, NULL, NULL)""",
                              (meeting_id, motion_item_order, motion_text))
            db.commit()
            
            irc.reply("Motion %d added to the current meeting" % motion_item_order)
                
        add = wrap(add, ['channel', 'text'])

        def list(self, irc, msg, args, channel):
            """[<channel>]
            
            List the motions for the current meeting in the channel
            """
            # get the current meeting ID
            meeting_id = meeting_singleton.get_current_meeting_id(channel)
            if meeting_id is None:
                irc.error("There is no current meeting in channel %s" % channel)
                return

            # get the database
            db = meeting_singleton.getDb(channel)

            # get the motion items
            cursor = db.cursor()            
            cursor.execute("""SELECT item_order, motion_text, 
                                     carries, votes_aye, votes_nay, decision_at
                              FROM motion
                              WHERE meeting_id=?
                              ORDER BY item_order ASC""", (meeting_id, ))
                       
            results = cursor.fetchall()

            if len(results)==0:
                irc.reply("The current meeting does not have any motions")
                return
            
            for item_order, motion_text, carries, aye, nay, decision_time in results:
                if carries is None:
                    carries_text = "Motion has not been up for vote yet"
                elif carries:
                    carries_text = "Motion carries, votes %d:%d at %s" % (aye, nay, decision_time)
                else:
                    carries_text = "Motion dismissed, votes %d:%d" % (aye, nay)
                irc.reply("Motion %d: %s - %s" % (item_order, motion_text, carries_text))
            
        list = wrap(list, ['channel'])

        def delete(self, irc, msg, args, channel, item_id):
            """[<channel>] <item_id>
            
            Delete a motion from the motion table, renumbering following motions.
            Cannot delete motions that have carried.
            """
            
            # get the current meeting ID
            meeting_id = meeting_singleton.get_current_meeting_id(channel)
            if meeting_id is None:
                irc.error("There is no current meeting in channel %s" % channel)
                return

            # get the database
            db = meeting_singleton.getDb(channel)

            # see how many we have now
            total_items = self.get_max_item_order(db, meeting_id)
            
            # check parameter
            if item_id > total_items:
                irc.error("Cannot delete the non-existent motion  %d" % item_id)
                return

            # check the motion being deleted, if it carries it can't be deleted
            
            cursor = db.cursor()            
            cursor.execute("""SELECT carries
                              FROM motion
                              WHERE meeting_id=?
                              AND item_order=?""", (meeting_id, item_id))
                       
            results = cursor.fetchall()

            if len(results)==0:
                irc.error("Something's wrong, this motion should have existed")
                return

            if results[0][0] is not None and result[0][0]:
                irc.error("Motion %d cannot be deleted because it has carried. It's not a time machine, James." % item_id)

            # do the delete
            cursor = db.cursor()
            cursor.execute("""DELETE FROM motion
                              WHERE meeting_id=?
                              AND item_order=?""", (meeting_id, item_id))
            
            # renumber the rest of the items
            for item in range(item_id+1, total_items+1):
                cursor.execute("""UPDATE motion
                                  SET item_order=?
                                  WHERE meeting_id=?
                                  AND item_order=?""", (item-1, meeting_id, item))
                
            db.commit()
            
            irc.reply("Motion %d has been deleted" % item_id)
            
        delete = wrap(delete, ['channel', 'positiveInt'])

Class = Meeting


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:

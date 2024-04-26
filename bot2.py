#!/bin/env python
import asyncio, os, psycopg2, time, datetime,re

from aiohttp import ClientWebSocketResponse
from mipac import Note
from datetime import timedelta
from mipac.models.notification import NotificationNote

from mipa.ext.commands.bot import Bot
def db_connect():
    return psycopg2.connect(database=os.environ["DB_DATABASE"],
                        host=os.environ["DB_HOST"],
                        user=os.environ["DB_USER"],
                        password=os.environ["DB_PASS"],
                        port=os.environ["DB_PORT"])
def rowToDict(row, col):
    res_dct = {col[i].name: row[i] for i in range(0, len(col))}
    return res_dct

def extract_time(timein=""):
    timein = timein.lower()
    time_match = re.search('(\d+)\s(\w*)', timein)
    remindtime = None
    hours = 0
    minutes = 0
    days = 0
    weeks = 0

    match time_match.group(2):
        case x if x in "hours":
            hours = time_match.group(1)
        case x if x in "minutes":
            minutes = time_match.group(1)
        case x if x in "days":
            days = time_match.group(1)
        case x if x in "weeks":
            weeks = time_match.group(1)            
        case x if x in "months": # convert
            days = int(30.41 * int(time_match.group(1)) )           
        case x if x in "years": # convert
            days = int(365.25 * int(time_match.group(1)) )

    remindtime = time.time() + timedelta(minutes=int(minutes),hours=int(hours),days=int(days), weeks=int(weeks)).total_seconds()

    return remindtime

async def timeout_callback():
    await asyncio.sleep(0.1)
    print('echo!')

class MyBot(Bot):
    def __init__(self):
        super().__init__()
        self.loop = asyncio.get_event_loop()

    async def start(
        self,
        url: str,
        token: str,        
    ):
       asyncio.create_task(bot.reminder_loop())
       await super().start(url,token)
    async def reminder_loop(self):
        await asyncio.sleep(20) # Add check that we're connected at some point
        while True:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute("select id, reminder_time,note_id, request_user from reminders where active='t' and reminder_time < now()")
            rows = cur.fetchall()
            cols = cur.description
            for row_raw in rows:
                row = rowToDict(row_raw,cols)
                rtime = row.get("reminder_time")
                note_id = row.get("note_id")
                id = row.get("id")
                request_user = row.get("request_user")
                print(row)
                try:
                    original_note = await self.client.note.action.get(note_id)
                    print(original_note)
                    await self.client.note.action.send("This is your reminder!",
                                                visibility="specified",reply_id=note_id)
                    cur.execute("DELETE from reminders where id = %s",(id,))
                    conn.commit()
                except Exception as ex:
                    print(f"Error processing reminder id:{id} noteID: {note_id}. Does it still exist?")
                    conn.rollback()
            conn.close()
            await asyncio.sleep(60)


    async def _connect_channel(self):
      await self.router.connect_channel(['main', 'home'])

    async def on_ready(self, ws: ClientWebSocketResponse):
        await self._connect_channel()
        print('Logged in ', self.user.username)
        print('Logged in ', self.user.instance)

    async def on_reconnect(self, ws: ClientWebSocketResponse):
        await self._connect_channel()

    async def process_message(self, note: Note):
        #stuff
        print("processing message")
        print(f'{note.author.username}: {note.content}')
        if('!remindme' in note.content or '@'+self.user.username in note.content):
            print("This is a reminder!")
            author =  await self.client.user.action.get(note.author.id)
            if(author.is_followed or '@'+self.user.username in note.content): #Get consent from user. Be a follower or at the bot
                conn = db_connect()
                userHost = os.environ["MISSKEY_HOST"]
                if(note.author.host):
                    userHost = note.author.host
                authorFull= f"@{note.author.username}@{userHost}"
                print(f"Reminder approved: {authorFull}")
                error = None
                try:
                    command = note.content.strip()
                    remind_time = extract_time(command)
                    timestamp = datetime.datetime.fromtimestamp(remind_time).strftime('%Y-%m-%d %H:%M:%S')
                    timezone = time.tzname[time.daylight]
                    reminderText=f"I will attempt to remind you at: {timestamp} {timezone}"
                    print(f"{authorFull}: {reminderText}")
                    cur = conn.cursor()
                except Exception as ex:
                    error = "Error parsing"
                    print("Error parsing reminder")
                try: 
                    cur.execute('insert into reminders (request_user, request_post, reminder_time, note_id) VALUES(%s,%s,%s,%s)',
                            (authorFull, note.uri, str(timestamp), note.id))
                except Exception as ex:
                    error = True
                    print(f"Error creating reminder: {ex}")
                    await self.client.note.action.send(content="Error creating reminder in DB", visibility=note.visibility,visible_user_ids=note.visible_user_ids,local_only=note.local_only,
                                                       reply_id=note.id)
                if(not error):
                    await self.client.note.action.send(content=reminderText, visibility=note.visibility,visible_user_ids=note.visible_user_ids,local_only=note.local_only,
                                                       reply_id=note.id)
                conn.commit()
                conn.close()
    async def on_mention(self, notice: NotificationNote):
        # When using this event, if you use MENTION_COMMAND, you must call this method for it to work.
        print(notice.note.content)
        await self.process_message(notice.note)
        await self.progress_command(notice)

    async def on_note(self, note: Note):  # This event receives all channel notes
        await self.process_message(note)

if __name__ == '__main__':
    bot = MyBot()
    asyncio.run(bot.start('wss://'+os.environ["MISSKEY_HOST"]+'/streaming', os.environ["API_KEY"]))

# bot.py
import os
import sys

import requests
# import tempfile

import re

import discord
from dotenv import load_dotenv

import openai
load_dotenv()

# Based on https://realpython.com/how-to-make-a-discord-bot-python/

DISCORD_MSG_LIMIT = 2000
OPENAI_HIST_LIMIT = 30

OPENAI_ERRORS = (openai.error.Timeout, openai.error.APIError, openai.error.APIConnectionError, openai.error.InvalidRequestError, openai.error.RateLimitError)

BOT_NAME = '@SmarterAdult'
CHAT_CHANNEL = 'bot-chat'

TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

def help_text():
    return f"""
How to use this bot

Post in the channel #{CHAT_CHANNEL}. The bot will respond to each message.

There are some special commands as well:
!reprompt - gives the bot a new prompt to follow. Example: `!reprompt You are a 1930s radio announcer who always speaks in hyperbole and loves alliteration.`
!bio - gives the bot some information about you. Example: `!bio @CoolGamer2k4 is a forensic accountant who lives in Manchester, UK.`
!reroll - has the bot come up with a new answer to the last prompt.
!restart - resets the chat history for this server.
!help (!h) - shows this message
"""

intents = discord.Intents.default()
intents.reactions = True
intents.message_content = True

client = discord.Client(intents=intents)

ur_prompt = "You are @SmarterAdult, a relaxed friendly dude. You are responding to multiple people, who you can tell apart by the username that appears at the beginning of their messages. You strive to treat them as individuals with different personalities."
message_hist_dict = {}

async def flush_messages(response_text, channel):
    while response_text:
        await channel.send(response_text[:DISCORD_MSG_LIMIT])
        response_text = response_text[DISCORD_MSG_LIMIT:]

async def get_api_response(message_hist):
    global ur_prompt
    completion = openai.ChatCompletion.create(
        model='gpt-4',
        messages=([{"role": "system", "content": ur_prompt}] + message_hist)
    )
    response_text = completion.choices[0].message.content
    return response_text

@client.event
async def on_ready():
    print("Ready")

@client.event
async def on_message(message):
    global message_hist_dict

    # Only interact with messages in the ChatGPT channel
    if message.channel.name != CHAT_CHANNEL:
        return

    # Don't respond to self
    if message.author == client.user:
        return

    if not message.clean_content:
        return

    if message.channel.id not in message_hist_dict:
        message_hist_dict[message.channel.id] = []
    message_hist = message_hist_dict[message.channel.id]

    if message.clean_content.strip() == '!help':
        await message.reply(help_text())
        return


    if message.clean_content.strip() == "!restart":
        message_hist_dict[message.channel.id] = []
        await message.reply("Chat history cleared")
        return

    if "!bio" in message.content:
        input_text = message.clean_content.replace('!bio', '').strip()
        bio_text = f"[You can tell users apart by the '@' in front of their usernames, which appear at the start of each of their messages. Here is what you know about the user known as '@{message.author.display_name}': {input_text}]"
        message_hist.append({"role": "system", "content": bio_text})
        await message.reply(f"Got it. I'll remember that about @{message.author.display_name}.")
        return

    if "!hist" in message.content:
        print(message_hist)
        return

    if "!reroll" in message.content:
        message_hist.pop()
    else:
        if "!gaslight" in message.content or "!reprompt" in message.content:
            message_author = 'system'
            input_text = 'New prompt: ' + message.clean_content.replace('!gaslight', '').replace('!reprompt', '').strip()
            print(input_text)
        else:
            message_author = 'user'
            input_text = f"@{message.author.display_name}: {message.clean_content}"
        message_hist.append({"role": message_author, "content": input_text})
        if len(message_hist) > OPENAI_HIST_LIMIT : message_hist.pop(0)

        print(f"Input: <{input_text}>")
    await message.add_reaction('⏳')

    try:
        response_text = await get_api_response(message_hist)
        print(f"Output: <{response_text}>")
        message_hist.append({"role": "system", "content": response_text})
        await flush_messages(response_text, message.channel)
    except OPENAI_ERRORS as e:
        print(e)
        await message.reply(f"Oops, there was an OpenAI error: `{type(e).__name__}: {e}`")
    finally:
        await message.remove_reaction('⏳', client.user)
    return

client.run(TOKEN)

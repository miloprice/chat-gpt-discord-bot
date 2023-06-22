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
!reroll - has the bot come up with a new answer to the last prompt.
!restart - resets the chat history for this server.
!help (!h) - shows this message
"""

token_dict = {}

def engine_for_server(server_id):
    global token_dict
    if server_id in token_dict and token_dict[server_id] > 0:
        return 'gpt-4-0613'
    else:
        return 'gpt-3.5-turbo-0613'

def token_pool_for_server(server_id):
    global token_dict
    if server_id in token_dict:
        return token_dict[server_id]
    else:
        return 0

def tokens_to_dollars(tokens):
    dollar_amount = tokens * 0.045 / 1000
    return format(dollar_amount, '.2f')

def dollars_to_tokens(dollars):
    return int(dollars / 0.045 * 1000)

def usage(server_id):
    global token_dict
    token_pool = token_pool_for_server(server_id)
    return f"""
Current engine: `{engine_for_server(server_id)}`
Remaining GPT-4 tokens: {token_pool} (about ${tokens_to_dollars(token_pool)})

This is a message from me, SmarterAdult - no GPT usage required.
"""

def paid(server_id, dollars):
    global token_dict
    if server_id not in token_dict:
        token_dict[server_id] = 0
    token_add = dollars_to_tokens(dollars)
    token_dict[server_id] += token_add
    return f"Great! ${dollars} was added to the tip jar.\n\n" + usage(server_id)


intents = discord.Intents.default()
intents.reactions = True
intents.message_content = True

client = discord.Client(intents=intents)

message_hist_dict = {}
prompt_dict = {}

async def flush_messages(response_text, channel):
    while response_text:
        await channel.send(response_text[:DISCORD_MSG_LIMIT])
        response_text = response_text[DISCORD_MSG_LIMIT:]

async def get_api_response(message, message_hist, first_prompt=None):
    messages = message_hist
    if first_prompt:
        messages = [{"role": "system", "content": first_prompt}] + messages
    response_text = None
    while response_text is None:
        try:
            server_id = message.channel.id
            engine = engine_for_server(server_id)
            completion = openai.ChatCompletion.create(
                model=engine,
                messages=messages
            )
            if engine == 'gpt-4-0613':
                token_usage = completion.usage.total_tokens
                token_dict[server_id] = max(0, token_dict[server_id] - token_usage)
                if token_dict[server_id] == 0:
                    await message.reply("You're now out of GPT-4 tokens. Switching to GPT-3.5.")
            print(completion)
            response_text = completion.choices[0].message.content
        except openai.error.InvalidRequestError as e:
            if message_hist: message_hist.pop(0)
            messages = message_hist
    return response_text

def is_reprompt(message_text):
    return message_text.strip().startswith("!reprompt") or message_text.strip().startswith("!gaslight")

@client.event
async def on_ready():
    print("Ready")

@client.event
async def on_message(message):
    global message_hist_dict
    global prompt_dict
    global token_dict

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

    if message.channel.id not in prompt_dict:
        prompt_dict[message.channel.id] = None

    if message.channel.id not in token_dict:
        token_dict[message.channel.id] = 0

    if message.clean_content.strip() == '!help':
        await message.reply(help_text())
        return

    if message.clean_content.strip() == "!restart":
        message_hist_dict[message.channel.id] = []
        prompt_dict[message.channel.id] = None
        await message.reply("Chat history cleared")
        return

    if message.clean_content.strip() == "!hist":
        print(message_hist)
        return

    if message.clean_content.strip() == "!ping":
        await message.reply("Pong")
        return

    if message.clean_content.strip() == '!usage':
        await message.reply(usage(message.channel.id))
        return

    if message.clean_content.strip().startswith('!paid'):
        tokens = message.clean_content.strip().split(' ')
        if len(tokens) != 2 or not tokens[1].replace('$', '').isdigit():
            await message.reply("Please use the format `!paid $10` or `!paid 10` - whole dollars only!")
            return
        dollar_amount = int(tokens[1].replace('$', ''))
        await message.reply(paid(message.channel.id, dollar_amount))
        return

    if message.clean_content.strip() == "!reroll":
        message_hist.pop()
    else:
        input_text = message.clean_content
        message_author = 'user'
        if is_reprompt(input_text):
            message_author = 'system'
            input_text = input_text.replace('!reprompt', '').replace('!gaslight', '').strip()
            print(f"New prompt: <{input_text}>")
            prompt_dict[message.channel.id] = input_text
            await message.add_reaction('🫡')
        message_hist.append({"role": message_author, "content": input_text})
        if len(message_hist) > OPENAI_HIST_LIMIT : message_hist.pop(0)

        print(f"Input: <{input_text}>")
    await message.add_reaction('⏳')

    try:
        response_text = await get_api_response(message, message_hist, prompt_dict[message.channel.id])
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

# bot.py
import os
import sys

import requests
import tempfile

import re

import discord
from dotenv import load_dotenv

import openai

load_dotenv()

# Based on https://realpython.com/how-to-make-a-discord-bot-python/

DISCORD_MSG_LIMIT = 2000
OPENAI_HIST_LIMIT = 30
IMAGE_TOKEN_LIMIT = 1000

OPENAI_ERRORS = (openai.error.Timeout, openai.error.APIError, openai.error.APIConnectionError, openai.error.InvalidRequestError, openai.error.RateLimitError)

BOT_NAME = '@SmarterAdult'
CHAT_CHANNEL = 'bot-chat'

TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

def help_text():
    return f"""
How to use this bot

Post in the channel #{CHAT_CHANNEL}. The bot will respond to each message. You may attach one or more images.

There are some special commands as well:
!draw <prompt> - has the bot generate an image based on the prompt.
!reprompt - gives the bot a new prompt to follow. Example: `!reprompt You are a 1930s radio announcer who always speaks in hyperbole and loves alliteration.`
!reroll - has the bot come up with a new answer to the last prompt.
!restart - resets the chat history for this server.
!help (!h) - shows this message
"""

def engine_for_server(server_id):
    return 'gpt-4-1106-preview'

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

async def get_api_response(message, message_hist, first_prompt=None, image_urls=None):
    messages = message_hist
    if first_prompt:
        messages = [{"role": "system", "content": first_prompt}] + messages
    response_text = None
    while response_text is None:
        try:
            server_id = message.channel.id
            engine = 'gpt-4-vision-preview' if image_urls else engine_for_server(server_id)
            max_tokens = IMAGE_TOKEN_LIMIT if image_urls else None
            completion = openai.ChatCompletion.create(
                model=engine,
                messages=messages,
                max_tokens=max_tokens
            )
            print(completion)
            response_text = completion.choices[0].message.content
        except openai.error.InvalidRequestError as e:
            if message_hist: message_hist.pop(0)
            messages = message_hist
    return response_text

async def get_image_url(prompt):
    try:
        response = openai.Image.create(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        print(response)
        return response.data[0].url, response.data[0].revised_prompt

    except openai.error.InvalidRequestError as e:
        await message.reply(str(e))

def is_reprompt(message_text):
    return message_text.strip().startswith("!reprompt") or message_text.strip().startswith("!gaslight")

def is_draw(message_text):
    return message_text.strip().startswith("!draw")

@client.event
async def on_ready():
    print("Ready")

@client.event
async def on_message(message):
    global message_hist_dict
    global prompt_dict

    # Only interact with messages in the ChatGPT channel
    if message.channel.name != CHAT_CHANNEL:
        return

    # Don't respond to self
    if message.author == client.user:
        return

    if message.clean_content.startswith('#') or message.clean_content.startswith('//'):
        return

    if message.channel.id not in message_hist_dict:
        message_hist_dict[message.channel.id] = []
    message_hist = message_hist_dict[message.channel.id]

    if message.channel.id not in prompt_dict:
        prompt_dict[message.channel.id] = None

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

    if is_draw(message.clean_content):
        await message.add_reaction('🎨')
        input_text = message.clean_content.replace('!draw', '').strip()
        print(f"Drawing: '{input_text}'")
        message_hist.append({"role": 'user', "content": [{"type": "text", "text": f"Draw {input_text}"}]})

        try:
            image_url, revised_prompt = await get_image_url(input_text)
            message_hist.append({"role": "system", "content": [{"type": "text", "text": f"<DALL-E 3 generated an image from the prompt: '{revised_prompt}'>"}]})

            image_data = requests.get(image_url).content
            with tempfile.NamedTemporaryFile(suffix='.png', mode='wb', delete=True) as temp_imagefile:
                temp_imagefile.write(image_data)
                temp_imagefile.seek(0)
                discord_file = discord.File(temp_imagefile.name)
                await message.reply(revised_prompt, file=discord_file)
            await message.remove_reaction('🎨', client.user)
        except OPENAI_ERRORS as e:
            print(e)
            await message.reply(f"Oops, there was an OpenAI error: `{type(e).__name__}: {e}`")
        finally:
            return

    # Extract images (TODO: maybe do this by content-type?)
    image_urls = [attachment.url for attachment in message.attachments if attachment.width]
    print(f"image_urls: {image_urls}")

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

        content = [{"type": "text", "text": input_text}]
        for image_url in image_urls:
            content.append({"type": "image_url", "image_url": image_url})
        message_hist.append({"role": message_author, "content": content})

        if len(message_hist) > OPENAI_HIST_LIMIT : message_hist.pop(0)
        print(f"Input: <{input_text}>")

    await message.add_reaction('⏳')

    try:
        response_text = await get_api_response(message, message_hist, prompt_dict[message.channel.id], image_urls)
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

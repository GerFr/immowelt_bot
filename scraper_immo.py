from bs4 import BeautifulSoup
import requests
import re
import json
import random

def get_titles(request_content: bytes)->object:
    soup = BeautifulSoup(request_content, 'html.parser')
    text = str(soup.find_all("h2"))
    text_seperated = [title.strip("</h2>").strip("[</h2>") for title in text.split("</h2>, ") if "[TAUSCHWOHNUNG]" not in title and "Wohnungsswap" not in title and not "class=" in title]
    formatted_text = ""
    for i, title in enumerate(text_seperated):
        formatted_text += f"{i+1:3}: {title}\n"
    return formatted_text


def get_data(request_content: bytes)->list:
    soup = BeautifulSoup(request_content, 'html.parser')
    return extract_jsons_from_string(str(soup))


def extract_jsons_from_string(data_string: str)-> list:
    first_index = []
    second_index = []
    valid_jsons = {}
    single_jsons = {}
    
    #get all possible indeces
    for index, char in enumerate(data_string):
        if char == '{':
            first_index.append(index)
        elif char == '}':
            second_index.append(index) 
              
    #get all indeces in right order 
    combinations = [(first, second) for second in second_index for first in first_index if first < second]

    #get all possible valid jsons, valid jsons in nested in larder jsons also get created
    for combination in combinations:
        string_range = data_string[combination[0]:combination[1]+1]
        try:
            json_range = json.loads(string_range)
            valid_jsons[string_range]=json_range
        except Exception as e:
            pass
    
    #get only outermost jsons from all valid jsons
    for json_key in valid_jsons.keys():
        add = True
        for other_key in valid_jsons.keys():
            if json_key in other_key and json_key != other_key:
                add = False
        if add: single_jsons[json_key] = valid_jsons[json_key]
    return list(single_jsons.values())


def get_local_jsons(directoy: str)-> list:
    text = ""  
    with open(directoy) as file:
        for line in file:
            text += line
    return extract_jsons_from_string(text)


def largest_json(list)-> dict:
    return max(list, key=lambda item: len(item.keys()))

def get_immo_data():
    r = requests.get("https://www.immowelt.de/suche/hamburg-ottensen/wohnungen/mieten?lat=53.5513&lon=9.92234&sr=3")
    request_content = r.content.decode('utf-8','ignore')
    immo_data = largest_json(get_data(request_content))["initialState"]["estateSearch"]["data"]["estates"]
    return immo_data


def extract_info(estate_data: dict)-> str:
    try:
        estate_info = ""
        estate_info += f"{estate_data['title']}"
        estate_info += f"\nArea: {estate_data['areas'][0]['sizeMin']}, Rooms: {estate_data['roomsMin']}"
        
        for pricing in estate_data["prices"]:
            estate_info += f"\n{pricing['type']}: {pricing['amountMin']} {pricing['currency']}"
        
        location_data = estate_data["place"]
        try: estate_info += f"\npostcode: {location_data['postcode']}, city: {location_data['city']}, district: {location_data['district']}"
        except: estate_info += f"\n no location data"

        estate_picture = random.choice(estate_data["pictures"])
        estate_info += f"\nPicture {estate_picture['description']}: {estate_picture['imageUri']}\n\n"
    except:
        estate_info = f"error in extracting data from estate \n\n"

    return estate_info



TOKEN = ""

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes

application = ApplicationBuilder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="I'm a bot, please talk to me!"
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for estate in get_immo_data():
        await context.bot.send_message(chat_id=update.effective_chat.id, text=extract_info(estate))

from telegram.ext import CommandHandler
start_handler = CommandHandler('start', start)

echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), echo)
application.add_handler(start_handler)
application.add_handler(echo_handler)
application.run_polling()
from bs4 import BeautifulSoup
import requests
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import CommandHandler
import pandas as pd
import plotnine as p9
import warnings
import logging


def get_creds(file_dir, length):
    with open(file_dir, "r") as file: return file.readline(length)

TOKEN = get_creds("token.txt", 46)
ADMIN_ID = int(get_creds("admin.txt", 10))
DEFAULT_URL = "https://www.immowelt.de/suche/wohnungen/mieten"
LOG_FILENAME = "scraper_immo.log"
LOG_LEVEL = logging.WARNING # everything lower shows telegrams logs aswell
LOG_LENGTH = 10
TEXT_INDENT = 25


warnings.filterwarnings('ignore')
logging.basicConfig(format='%(asctime)s %(message)s',
                    filename=LOG_FILENAME, 
                    encoding='utf-8', 
                    level=LOG_LEVEL, 
                    filemode='w')

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


def get_data(request_content: bytes)->list:
    soup = BeautifulSoup(request_content, 'html.parser')
    return extract_jsons_from_string(str(soup))


def largest_json(list)-> dict:
    return max(list, key=lambda item: len(item.keys()))


def get_url(message: str)->str:
    return f"https://www.immowelt.de/suche/{message}/wohnungen/mieten"


def get_immo_data(url):
    try:
        r = requests.get(url)
        request_content = r.content.decode('utf-8','ignore')
        immo_data = largest_json(get_data(request_content))
        with open("remote_json.json", "w") as file:
            json.dump(immo_data, file)
        return immo_data["initialState"]["estateSearch"]["data"]["estates"]
    except Exception as e:
        logging.error(f"Failed to fetch data from url: {url}")
        return None
 

def filter_estates(keywords:list, estates:dict, category:str)->list:
    return [estate for estate in estates if all([keyword not in estate[category] for keyword in keywords])] 


def sort_estates(estates:dict)->dict:
    def sort_key(estate:dict)->dict:
        try: return estate["prices"][0]["amountMin"]
        except: return float("inf")
    return sorted(estates, key = sort_key)




def format_md(data:str)->str:
    for character in "._(),*[]~>`#+-=|{}!":
        data = data.replace(character, f'\{character}')
    return data


def get_md(estate:dict, *args)->str:
    try:
        value = estate
        for argument in args:
            value = value[argument]
        return format_md(str(value))
    except Exception as e:
        string_arguments = ", ".join([str(arg) for arg in args])
        logging.error(f"Data exstraction failed for {estate['id']} and {string_arguments}")
        return "no data"


def extract_info(estate_data: dict)-> str:
    try:
        estate_info = ""
        estate_info += (
        f"{get_md(estate_data,'title')}\n"+

        "\n```"+
        f"\n{'id'}\t{get_md(estate_data,'id')}"+
        f"\n{'area':{TEXT_INDENT}}{get_md(estate_data,'areas',0,'sizeMin')}"+
        f"\n{'Rooms':{TEXT_INDENT}}{get_md(estate_data,'roomsMin')}")
        
        for pricing in estate_data["prices"]:
            search = "\_"
            pricing_type = get_md(pricing,'type').lower().replace(search, ' ')
            estate_info += (
            f"\n{pricing_type:{TEXT_INDENT}}"+
            f"{get_md(pricing,'amountMin')} {get_md(pricing,'currency')}")
         
        location_data = estate_data["place"]
        estate_info += (
        f"\n{'postcode':{TEXT_INDENT}}{get_md(location_data,'postcode')}"+
        f"\n{'city':{TEXT_INDENT}}{get_md(location_data,'city')}"+
        f"\n{'district':{TEXT_INDENT}}{get_md(location_data,'district')}"+
        "\n```")

        return estate_info + format_md(f"\nhttps://www.immowelt.de/expose/{estate_data['onlineId']}\n\n")
    
    except: 
        message = f"String creation failed for {estate_data['id']}"
        logging.error(message)
        return None
    
    
def get_series(estate_data: dict)->pd.Series:
    try:
        cold = estate_data["prices"][0]
        warm = estate_data["prices"][1] if len(estate_data["prices"])>1 else {"amountMin":None}
        location_data = estate_data["place"]
        
        #change default values, use get
        area = estate_data["areas"][0]["sizeMin"]
        return pd.Series({
            "id":estate_data["id"], 
            "area":area,"rooms":str(estate_data["roomsMin"]), 
            "cold": cold["amountMin"], 
            "warm": warm["amountMin"], 
            "district":location_data["district"]})
    
    except Exception as e:
        logging.error(f"Series creation failed for {estate_data['id']}")
        return pd.Series()


def get_dataframe(series_list:list)->pd.DataFrame:
    return pd.DataFrame([*series_list])


def create_images(estate_dataframe:pd.DataFrame)->list:
    estate_dataframe['area_average']=estate_dataframe['area'].apply(func=lambda area: (str(len(str((area//50)*50)))+": "+str((area//50)*50)))
    
    plots = [
    (p9.ggplot(estate_dataframe, p9.aes(x='rooms', y='cold', fill='rooms')) 
        + p9.geom_violin(draw_quantiles=0.5, trim=False)
        + p9.scale_fill_brewer(type='qual')
        + p9.theme_minimal()),
    (p9.ggplot(estate_dataframe) 
        + p9.aes(x="rooms", fill="rooms") 
        + p9.geom_bar()
        + p9.theme_minimal()),
    (p9.ggplot(estate_dataframe) 
        + p9.aes(x="district", fill="district") 
        + p9.geom_bar()
        + p9.theme_minimal()),
    (p9.ggplot(estate_dataframe, p9.aes(x='area_average', y='cold', fill='area_average')) 
        + p9.geom_violin(draw_quantiles=0.5, trim=False)
        + p9.scale_fill_brewer(type='qual')
        + p9.theme_minimal()),
    (p9.ggplot(estate_dataframe, p9.aes(x='rooms', y='area', fill='rooms')) 
        + p9.geom_violin(draw_quantiles=0.5, trim=False)
        + p9.scale_fill_brewer(type='qual')
        + p9.theme_minimal())]
    
    images = []
    for i, plot in enumerate(plots):
        name = f'img{i}.png'
        plot.save(filename = name, height=5, width=5, units = 'in', dpi=1000)
        images.append(name)
    return images


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Hi {name}, say anything..."
    )

async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID != update.effective_user.id:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Not authentification")
        logging.warning(f"Log view attempt by {update.effective_user.name}")
        return None
    try:
        with open(LOG_FILENAME, "r") as logs:
            log_messages = [log for log in logs]
        message = "```\n"+format_md(''.join(log_messages[-LOG_LENGTH:]))+"\n```"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='MarkdownV2')
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="failed getting log data")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message.text
    user = update.effective_user
    logging.warning(f"Request by {user.name} for {message}")
    message_url = get_url(message)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Hi {user.first_name},\nlooking into the following Url:\n{message_url}")
    estate_list = get_immo_data(message_url)
    
    if  not estate_list: 
        await context.bot.send_message(chat_id=update.effective_chat.id, 
        text=f"You used an invalid location, go here to search:\n{DEFAULT_URL}\ntry these locations:\nberlin-charlottenburg\nkoeln-porz\nhamburg-ottensen...")
    else: 
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"analysis...")
        
        filtered_estates = sort_estates(filter_estates(["[TAUSCHWOHNUNG]","Wohnungsswap"], estate_list, "title"))
        messages = [message for message in [extract_info(estate) for estate in filtered_estates] if message]
        estate_dataframe = get_dataframe([get_series(estate) for estate in filtered_estates])
        images = create_images(estate_dataframe)
        
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"sending...")
        for image in images:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(image, 'rb'))
        for message in messages:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='MarkdownV2')

    await context.bot.send_message(chat_id=update.effective_chat.id, text="Done!")


application = ApplicationBuilder().token(TOKEN).build()

start_handler = CommandHandler('start', start)
log_handler = CommandHandler('logs', logs)
echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), echo)
application.add_handler(start_handler)
application.add_handler(log_handler)
application.add_handler(echo_handler)

application.run_polling()

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
warnings.filterwarnings('ignore')


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
        return None
 

def filter_estates(keywords:list, estates:dict, category:str)->list:
    return [estate for estate in estates if all([keyword not in estate[category] for keyword in keywords])] 


def sort_estates(estates:dict)->dict:
    return sorted(estates, key = lambda estate: estate["prices"][0]["amountMin"])


def extract_info(estate_data: dict)-> str:
    try: #use get instead
        estate_info = ""
        estate_info += (
        f"{estate_data['title']}\n"+"```"+
        f"\n{'id:'}\t{estate_data['id']}"+
        f"\n{'area:':<30}{estate_data['areas'][0]['sizeMin']}"+
        f"\n{'Rooms:':<30}{estate_data['roomsMin']}")
        
        for pricing in estate_data["prices"]:
            estate_info += (
            f"\n{pricing['type'].lower().replace('_', ' ')+':':30}"+
            f"{pricing['amountMin']} {pricing['currency']}")
         
        try: 
            location_data = estate_data["place"]
            estate_info += (
            f"\n{'postcode:':<30}{location_data['postcode']}"+
            f"\n{'city:':<30}{location_data['city']}"+
            f"\n{'district:':<30}{location_data['district']}")
        except: 
            estate_info += f"\n no location data"

        estate_info += ("\n```"+
        f"\nhttps://www.immowelt.de/expose/{estate_data['onlineId']}\n\n")

        return estate_info
    
    except: 
        print(f"String creation failed for {estate_data['id']}")
        return f"\nerror in extracting data from estate \n\n"

    
def get_series(estate_data: dict)->pd.Series:
    try:
        cold = estate_data["prices"][0]
        warm = estate_data["prices"][1] if len(estate_data["prices"])>1 else {"amountMin":None}
        location_data = estate_data["place"]
        
        #change default values, use get
        area = estate_data["areas"][0]["sizeMin"] #if len(estate_data["areas"])>0 else 50
        return pd.Series({
            "id":estate_data["id"], 
            "area":area,"rooms":str(estate_data["roomsMin"]), 
            "cold": cold["amountMin"], 
            "warm": warm["amountMin"], 
            "district":location_data["district"]})
    
    except Exception as e:
        print(f"Series creation failed for {estate_data['id']}")
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


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message.text
    message_url = get_url(message)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Hi {update.effective_user.first_name},\nlooking into the following Url:\n{message_url}")
    estate_list = get_immo_data(message_url)
    
    if  not estate_list: 
        await context.bot.send_message(chat_id=update.effective_chat.id, 
        text=f"You used an invalid location, go here to search:\n{DEFAULT_URL}\ntry these locations:\nberlin-charlottenburg\nkoeln-porz\nhamburg-ottensen...")
    else: 
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"analysis...")
        
        filtered_estates = sort_estates(filter_estates(["[TAUSCHWOHNUNG]","Wohnungsswap"], estate_list, "title"))
        messages = [extract_info(estate) for estate in filtered_estates]
        estate_dataframe = get_dataframe([get_series(estate) for estate in filtered_estates])
        images = create_images(estate_dataframe)
        
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"sending...")
        for image in images:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(image, 'rb'))
        for message in messages:
            for character in "._(),*[]~>#+-=|{}!":
                message = message.replace(character, f'\{character}')
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='MarkdownV2')

    await context.bot.send_message(chat_id=update.effective_chat.id, text="Done!")


def get_token(file_dir):
    with open(file_dir, "r") as file: return file.readline(46)


TOKEN = get_token("token.txt")
DEFAULT_URL = "https://www.immowelt.de/suche/wohnungen/mieten"

application = ApplicationBuilder().token(TOKEN).build()

start_handler = CommandHandler('start', start)
echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), echo)
application.add_handler(start_handler)
application.add_handler(echo_handler)
application.run_polling()

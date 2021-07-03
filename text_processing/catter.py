import os, time, sys, getopt
from bs4 import BeautifulSoup

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, func

import nltk
from nltk import sent_tokenize
from nltk import word_tokenize
from nltk.probability import FreqDist
from nltk.corpus import stopwords
from wordcloud import WordCloud
import matplotlib.pyplot as plt

import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

totalSites = 0



"""
******************
script entry point
******************
"""
# set to database credentials/host
# taken from local environment variable in the format postgresql+psycopg2://localuser:localuser@localhost/a11ymon
CONNECTION_URI = os.getenv("DATABASE_URL")
# need to fudge this for now as VCAP_SERVICES has the URI as postgres:... instead of postgresql:
if(CONNECTION_URI[:9] == "postgres:"):
    fudged_connection_uri = "postgresql" + CONNECTION_URI[8:]
else:
    fudged_connection_uri = CONNECTION_URI

print(fudged_connection_uri)

print("Connecting to database...")
engine = create_engine(fudged_connection_uri, connect_args={'options': '-csearch_path=analytics'})

Base = automap_base()

# reflect the tables
Base.prepare(engine, reflect=True)

# mapped classes are now created with names by default
# matching that of the table name.
websites = Base.classes.website_content

session = Session(engine)

##########
# Set up process flags
do_cleanup = False
do_visualisation = False
do_singlesite = False


def cleanup(website_id):
    global stopwords
    # fetch raw text & title
    text=" "
    title=" "
    description = ""
    logger.debug("cleaning " + str(current_website_id))
    query=session.query(websites).filter(websites.website_id == website_id)
    raw_text = query.one().home_page_raw
    soup = BeautifulSoup(raw_text, 'html.parser')
    if(soup.title):
        title = soup.title.string
    if(soup.body):
        text = soup.body.get_text("|", strip=True)
    for tag in soup.find_all("meta"):
        if tag.get("name", None) == "description":
            description = tag.get("content", None)
    if text is None:
        text=""
    if title is None:
        title = ""
    if description is None:
        description = ""
    logger.debug("saving '" + title + "'...")
    session.query(websites).filter(websites.website_id == website_id).update({"home_page_title": title, "home_page_body": text, "home_page_description": description})
    session.commit()
    logger.debug("saved '" + title)

def visualise(website_id):
    global stopwords

    query = session.query(websites).filter(websites.website_id == website_id)
    text = query.one().home_page_title + '|' + query.one().home_page_description + '|' + query.one().home_page_body

    #Tokenize the text with words :
    words = word_tokenize(text)

    # List of stopwords
    stopwords = stopwords.words("english")
    #print(stopwords)

    # Empty list to store words:
    words_no_punc = []
    # Removing punctuation marks :
    for w in words:
        if w.isalpha():
            words_no_punc.append(w.lower())

    # Empty list to store clean words :
    clean_words = []

    for w in words_no_punc:
        if w not in stopwords:
            clean_words.append(w)

    # Frequency distribution :
    fdist = FreqDist(clean_words)

    print(fdist.most_common(10))

    #Generating the wordcloud :
    wordcloud = WordCloud().generate(text)

    # Plot the wordcloud :
    plt.figure(figsize=(8, 8))
    plt.imshow(wordcloud)

    # To remove the axis value :
    plt.axis("off")
    plt.show()


def doStuff(current_website_id):
    global do_cleanup, do_visualisation, do_singlesite
    logger.debug("doing stuff with " + str(current_website_id))
    if (do_cleanup):
        cleanup(current_website_id)
    if (do_visualisation & do_singlesite):
        visualise(current_website_id)

"""
**********************************************
doTheLoop - cycle through all sites to process
**********************************************
"""

def doTheLoop():
    global current_website_id, totalSites

    logger.info("Selecting data...")
    # pick a url at random
    for current_website_id, home_page_url in session.query(websites.website_id, websites.home_page_url).filter(websites.home_page_body == None):
        print("Processing " + home_page_url)
        logger.debug("Processing " + home_page_url)

        totalSites += 1
        doStuff(current_website_id)
        print()
        print("****************************")
        print("Site number ", totalSites)
        print("****************************")
        print()

    print(".")
    print("****************************")
    print("Total tests: ", totalSites)
    print("****************************")


def main(argv):
    global current_website_id
    global do_cleanup, do_visualisation, do_singlesite
    singleSite = ''
    usage = 'Usage: catter.py -s <url> -[cv]'

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hs:cv", ["singleSite="])
    except getopt.GetoptError:
        print('error in command line. ' + usage)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(usage)
            sys.exit()
        if opt in ("-s", "--singleSite"):
            do_singlesite = True
            singleSite = arg
            logger.info('single url to retrieve is ' + singleSite)
        if opt in ("-c", "--cleanup"):
            do_cleanup = True
        if opt in ("-v", "--visualise"):
            do_visualisation = True


    if singleSite:
        print("Single Site: ", singleSite)
        query = session.query(websites).filter(websites.home_page_url == singleSite)
        current_website_id = query.one().website_id
        # do the thing...
        doStuff(current_website_id)
    else:
        doTheLoop()


if __name__ == "__main__":
    main(sys.argv[1:])



import os, sys, getopt

import pylab as p
from bs4 import BeautifulSoup

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, func
from sqlalchemy.dialects import postgresql

import nltk
from nltk import word_tokenize
from nltk.probability import FreqDist
from nltk.stem import PorterStemmer
from nltk.corpus import stopwords

import numpy as np
from wordcloud import WordCloud
import matplotlib.pyplot as plt

from sklearn import svm
from sklearn.model_selection import train_test_split
from sklearn import metrics

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
is_on_paas = os.getenv("CF_INSTANCE_GUID")
print("is_on_paas", is_on_paas)

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

# mapped classes are created with names by default
# matching that of the table name.
websites = Base.classes.website_content
bags_o_words = Base.classes.bags_o_words
term_document_matrix = Base.classes.term_document_matrix

session = Session(engine)

##########
# Set up process flags
do_cleanup = False
do_visualisation = False
do_singlesite = False
do_destop = False
do_stemmify = False
do_generate_keywords = False
do_generate_tdm = False
do_generate_svm = False
do_predict = False


def cleanup(website_id):
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
        text = text.encode('utf-8', 'replace').decode() # the encode/decode is to catch any illegal utf surrogates (yes, there are webpages with them in...)
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
    logger.debug("Description=" + description)
    session.query(websites).filter(websites.website_id == website_id).update({"home_page_title": title, "home_page_body": text, "home_page_description": description})
    session.commit()
    logger.debug("saved '" + title)

def destop(website_id):
    # fetch body text
    text=" "
    logger.debug("destopping " + str(current_website_id))
    query=session.query(websites).filter(websites.website_id == website_id)


    raw_text = query.one().home_page_raw
    soup = BeautifulSoup(raw_text, 'html.parser')
    if(soup.title):
        title = soup.title.string
    if(soup.body):
        text = soup.body.get_text("|", strip=True)
        text = text.encode('utf-8', 'replace').decode() # the encode/decode is to catch any illegal utf surrogates (yes, there are webpages with them in...)
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
    logger.debug("Description=" + description)
    session.query(websites).filter(websites.website_id == website_id).update({"home_page_title": title, "home_page_body": text, "home_page_description": description})
    session.commit()
    logger.debug("saved '" + title)

def generate_keywords(organisation_type_id):
    global stopwords, is_on_paas
    print("generating keywords for ", str(organisation_type_id))
    text = ""

    # concatenate all the text into one big lump - hope it doesn't run out of memory...
    for home_page_title, home_page_description, home_page_body in session.query(websites.home_page_title, websites.home_page_description, websites.home_page_body).filter(websites.organisation_type_id_known == organisation_type_id):
        if(home_page_title is not None):
            text = text + home_page_title + ' '
        if(home_page_description is not None):
            text = text + home_page_description + ' '
        if(home_page_body is not None):
            text = text + home_page_body + ' '

    #Tokenize the text with words :
    words = word_tokenize(text)

    # Empty list to store words:
    words_no_punc = []
    print("Removing punctuation marks")
    for w in words:
        if w.isalpha():
            words_no_punc.append(w.lower())

    # Get list of stopwords
    stopwords_list = stopwords.words("english")
    common_webby_words = ["contact", "us", "website", "cookies", "cookie", "find", "use",
                          "also", "sitemap", "please", "search", "email", "see", "would", "browser", "online",
                          "january", "february", "march", "april", "may", "june", "july",
                          "august", "september", "october", "november", "december",
                          ]
    for w in common_webby_words:
        stopwords_list.append(w)
    #print(stopwords_list)

    # Empty list to store clean words :
    clean_words = []
    print("Removing stopwords")
    for w in words_no_punc:
        if w not in stopwords_list:
            clean_words.append(w)

    porter = PorterStemmer()
    stemmed_words = []
    for w in clean_words:
        stemmed_words.append(porter.stem(w))

    final_words = stemmed_words # change to exclude steps e.g. clean_words,. words_no_punc

    print("Most common words:")
    # Frequency distribution :
    fdist = FreqDist(final_words)

    most_common_words = fdist.most_common(30)
    print(most_common_words)

    # update db
    # delete any that are already defined
    session.query(bags_o_words).filter(bags_o_words.organisation_type_id == organisation_type_id).delete()
    session.commit()

    word_index=0
    for w, freq in most_common_words:
        word_index +=1
        session.add_all(
            [
                bags_o_words(
                    organisation_type_id=organisation_type_id,
                    word=w,
                    frequency=freq,
                    word_index=word_index
                )
            ]
        )
        session.flush()
    session.commit()

    if(is_on_paas is None):
        #Generate a wordcloud:
        wordcloud = WordCloud().generate(' '.join(clean_words))

        # Plot the wordcloud :
        plt.figure(figsize=(8, 8))
        plt.imshow(wordcloud)

        # To remove the axis value :
        plt.axis("off")
        plt.show()


def make_tdm(organisation_type_id, mode="train"):
    print("making TDM in", mode, "mode")
    site_count = 0
    # create the term-document matrix for the supplied org-type

    # get the bag-o-words for this org-type
    bag_o_words = []
    for word, word_id in session.query(bags_o_words.word, bags_o_words.word_index).filter(bags_o_words.organisation_type_id == organisation_type_id):
        bag_o_words.append([word,word_id])
    print(bag_o_words)

    if(mode=="train"):
        # delete any entries for this org_type
        session.query(term_document_matrix).filter(term_document_matrix.organisation_type_id == organisation_type_id).delete()
        session.commit()

        # select all sites in this org-type
        result = session.query(websites).filter(websites.organisation_type_id_known == organisation_type_id)
        for row in result:
            site_count +=1
            text=""
            if(row.home_page_title is not None):
                text = text + row.home_page_title + ' '
            if(row.home_page_description is not None):
                text = text + row.home_page_description + ' '
            if(row.home_page_body is not None):
                text = text + row.home_page_body + ' '
            write_tdm_row(organisation_type_id, row.website_id, text, bag_o_words)


        # select an equal number of random sites definitely not in this org-type.
        result = session.query(websites).filter(websites.organisation_type_id_known != organisation_type_id).order_by(func.random()).limit(site_count)
        for row in result:
            site_count += 1
            text = ""
            if (row.home_page_title is not None):
                text = text + row.home_page_title + ' '
            if (row.home_page_description is not None):
                text = text + row.home_page_description + ' '
            if (row.home_page_body is not None):
                text = text + row.home_page_body + ' '
            write_tdm_row(organisation_type_id, row.website_id, text, bag_o_words)
    elif(mode=="predict"):
        print("Making TDM for all unknown sites")
        # NB. It's not necessary to delete existing entries when predicting for this org_type as they'll have been deleted when the training was run
        # select all sites not yet categorised
        result = session.query(websites).filter(websites.organisation_type_id_known == None)
        for row in result:
            site_count += 1
            text = ""
            if (row.home_page_title is not None):
                text = text + row.home_page_title + ' '
            if (row.home_page_description is not None):
                text = text + row.home_page_description + ' '
            if (row.home_page_body is not None):
                text = text + row.home_page_body + ' '
            write_tdm_row(organisation_type_id, row.website_id, text, bag_o_words)


def write_tdm_row(organisation_type_id, website_id, text, bag_o_words):
    # write a row in the tdm for given site and given orgtype -
    # this should be called for both sites known to be in that orgtype and known NOT to be in that orgtype
    #print(organisation_type_id, website_id)

    #Tokenize the text with words :
    words = word_tokenize(text)

    # Empty list to store words:
    words_no_punc = []

    for w in words:
        if w.isalpha():
            words_no_punc.append(w.lower())

    porter = PorterStemmer()
    stemmed_words = []
    for w in words_no_punc:
        stemmed_words.append(porter.stem(w))

    final_words=[]
    # Frequency distribution :
    fdist = FreqDist(stemmed_words)

    for bow, bow_id in bag_o_words:
        bow_freq=0
        for w, f in fdist.items():
            if (w==bow):
                bow_freq=f
        #print(bow_id, bow, bow_freq)

        session.add_all(
            [
                term_document_matrix(
                    organisation_type_id=organisation_type_id,
                    website_id=website_id,
                    frequency=bow_freq,
                    word_index=bow_id
                )
            ]
        )
        session.flush()

    session.commit()

def make_svm(organisation_type_id):
    global do_predict

    # fetch tdm for org-type
    labels = []
    website_ids = []
    # fetch labels - whether the site is known to be in this orgtype or not
    result = session.query(term_document_matrix.organisation_type_id, websites.website_id, websites.organisation_type_id_known)\
        .join(websites, term_document_matrix.website_id == websites.website_id).filter(term_document_matrix.organisation_type_id == organisation_type_id)\
        .order_by(term_document_matrix.website_id).distinct()
    for row in result:
        #print(row.website_id, row.organisation_type_id, row.organisation_type_id_known)
        member = 1 if (row.organisation_type_id == row.organisation_type_id_known) else 0
        labels.append(member)
        website_ids.append(row.website_id)

    targets = np.array(labels)

    logger.debug("********* fetching website IDs from Term-Document Matrix **************")
    result = session.query(term_document_matrix.website_id).\
        filter(term_document_matrix.organisation_type_id == organisation_type_id).\
        order_by(term_document_matrix.website_id).distinct()

    X = np.zeros(shape=(result.count(),30))
    counter=0

    for row in result:
        current_website_id = row.website_id
        #logger.debug("website #" + str(counter) + "id=" + str(current_website_id))

        line = np.empty(shape=(30))
        result = session.query(term_document_matrix).\
                filter(organisation_type_id == organisation_type_id).\
                filter(term_document_matrix.website_id==current_website_id).\
                order_by(term_document_matrix.word_index)
        for row in result:
            #print(counter, current_website_id, row.word_index, row.frequency)
            line[row.word_index-1] = row.frequency
            #print(line)

        X[counter] = line
        counter +=1

    features=X

    # define the classifier we're going to use.
    # We'll stick to a linear kernel and a default C of 1
    clf = svm.SVC(kernel='linear', C=1.0)

    X_train, X_test, y_train, y_test = train_test_split(features, targets, test_size=0.3, random_state=10)  # 70% training and 30% test

    # Train the model using the training set
    clf.fit(X_train, y_train)

    # Predict the response for test dataset
    y_pred = clf.predict(X_test)
    #print(y_pred)

    print("Accuracy:", metrics.accuracy_score(y_test, y_pred))

    # Model Precision: what percentage of positive tuples are labeled as such?
    print("Precision:",metrics.precision_score(y_test, y_pred))

    # Model Recall: what percentage of positive tuples are labelled as such?
    print("Recall:",metrics.recall_score(y_test, y_pred))

    # Model F1: balance of precision to recall
    f1 = metrics.f1_score(y_test, y_pred)
    print("F1:",f1)

    conf_matrix = metrics.confusion_matrix(y_test, y_pred)
    print(conf_matrix)

    if (do_predict):
        print("Polishing the crystal ball...")
        if(f1>0.9):
            predict(clf, organisation_type_id)
        else:
            print("**** model F1 only ", str(f1), ". Not accurate enough! Try creating a new TDM.")


def predict(clf, organisation_type_id):
    # check if there's entries in the TDM for websites not yet tested for this sector
    tdm_count = session.query(term_document_matrix, websites)\
        .join(websites, term_document_matrix.website_id == websites.website_id).\
        filter(term_document_matrix.organisation_type_id == organisation_type_id).\
        filter(websites.organisation_type_id_known == None).count()

    #logger.debug(str(result.statement.compile(dialect=postgresql.dialect())))
    print("tdm count", str(tdm_count))
    if tdm_count == 0:
        # populate the TDM
        make_tdm(organisation_type_id, "predict")

    # pass in all the unknown websites to the model
    # todo: consider re-evaluating the categorisation of already-categorised sites by passing in all but those already known to be this type (or heck, just all of them!)
    result = session.query(websites).filter(websites.organisation_type_id_known == None)
    print("Number of unknown sites:", result.count())
    x_predict = np.zeros(shape=(result.count(), 30))


    counter=0
    website_ids = []
    website_urls = []
    for row in result:
        current_website_id = row.website_id
        website_ids.append(current_website_id)
        website_urls.append(row.home_page_url)
        #print("website #", str(counter), "orgtype=", organisation_type_id, "id=", str(current_website_id), " url=", row.home_page_url)

        # lookup word distribution in the TDM
        line = np.empty(shape=(30))
        result = session.query(term_document_matrix).\
                filter(term_document_matrix.organisation_type_id == organisation_type_id).\
                filter(term_document_matrix.website_id==current_website_id).\
                order_by(term_document_matrix.word_index)
        #logger.debug(str(result.statement.compile(dialect=postgresql.dialect())))
        for row in result:
            #print(counter, current_website_id, row.word_index, row.frequency)
            line[row.word_index-1] = row.frequency

        #print(line)
        x_predict[counter] = line
        counter +=1

    print("predicting...")
    y_pred = clf.predict(x_predict)
    #logger.debug(y_pred)

    i=0
    for is_this_orgtype in y_pred:
        if(is_this_orgtype==1):
            website_id = website_ids[i]
            print("Got one!", website_urls[i])
            session.query(websites).filter(websites.website_id == website_id).update(
                {"organisation_type_id_predicted": organisation_type_id})
            session.commit()

        i+=1


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
    global do_cleanup, do_visualisation, do_singlesite, do_destop, do_stemmify
    logger.debug("doing stuff with " + str(current_website_id))
    if (do_cleanup):
        cleanup(current_website_id)
    if (do_destop):
        destop(current_website_id)
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
    for current_website_id, home_page_url in session.query(websites.website_id, websites.home_page_url):
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
    global do_cleanup, do_visualisation, do_singlesite, do_destop, do_stemmify, do_generate_keywords, do_generate_tdm, do_generate_svm, do_predict
    singleSite = ''
    usage = 'Usage: catter.py -s <url> -[hcvoek:t:x:p:s:] <orgtype>'

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hs:cvoek:t:x:p:", ["singleSite=", "orgtype="])
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
        if opt in ("-o", "--destop"):
            do_destop = True
        if opt in ("-v", "--visualise"):
            do_visualisation = True
        if opt in ("-k", "--keywords"):
            do_generate_keywords = True
            orgtype = arg
        if opt in ("-t", "--tdm"):
            do_generate_tdm = True
            orgtype = arg
        if opt in ("-x", "--svm"):
            do_generate_svm = True
            orgtype = arg
        if opt in ("-p", "--predict"):
            do_predict = True
            orgtype = arg


    if singleSite:
        print("Single Site: ", singleSite)
        query = session.query(websites).filter(websites.home_page_url == singleSite)
        current_website_id = query.one().website_id
        # do the thing...
        doStuff(current_website_id)
    elif do_generate_keywords:
        if(orgtype=="all"):
            for organisation_type in session.query(websites.organisation_type_id_known).distinct().filter(websites.organisation_type_id_known != None):
                print("generate keywords for ", organisation_type.organisation_type_id_known)
                generate_keywords(organisation_type.organisation_type_id_known)
        else:
            generate_keywords(orgtype)
    elif do_generate_tdm:
        make_tdm(orgtype)
    elif do_generate_svm:
        make_svm(orgtype)
    elif do_predict:
        # make the svm then call predict(), passing the resulting svm model
        make_svm(orgtype)
    else:
        doTheLoop()


if __name__ == "__main__":
    main(sys.argv[1:])



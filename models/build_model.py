# import 
import sys
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.ml.feature import StringIndexer, VectorAssembler, Normalizer
from pyspark.ml.feature import OneHotEncoderEstimator
from pyspark.sql.functions import udf
from pyspark.sql.types import IntegerType, StringType
from pyspark.sql.functions import to_date, datediff
from pyspark.sql.functions import lit, avg, when, count, col, min, max, round
from pyspark.sql import Window
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml import Pipeline
from pyspark.mllib.evaluation import MulticlassMetrics

def load_data(path):
    '''
    Function, which loads dataset
    
    INPUT:
        path - path to json file, which contains Sparkify data
        
    OUTPUT:
        df - ataframe, which contains dataset
        spark - initiate spark context
    '''
    spark = SparkSession.builder \
    .master("local") \
    .appName("Sparkify_Model") \
    .getOrCreate()
    
    df = spark.read.json(path)
    df.persist()
    
    return spark, df

def clean_data(df):
    '''
    Function which performs data cleaning of Sparkify dataset.
    
    INPUT: 
    df - df containing user event data
    
    OUTPUT:
    df_new
    '''
    
    # remove rows where userId is empty
    df_new = df.filter(df["userId"] != "")
    
    return df_new

def prepare_dataset(df):
    '''
    Function to prepare data for model training by further cleaning and feature engineering
    
    INPUT:
    df - initial dataset loaded from json file
    
    OUTPUT:
    df_ml - new dataset prepared for machine learning
    contains the following columns:
    1. userId - initial id of the user
    2. gender - user's gender
    3. avg_events - average number of events per day for the user
    4. avg_songs - average number of songs the user listens to per day
    5. thumbs_up - number of thumbs up events
    6. thumbs_down - number of thumbs down events
    7. active_days - days since user's firts event
    8. last_location - location of the last event
    9. last_level - user's last level (paid or free)
    10. addfriends - number of add friends events
    '''
    
    # clean dataset using clean_data function
    df = clean_data(df)
    
    # add 'churn' column to the original dataset
    
    # define cancellation udf
    cancellation_event = udf(lambda x: 1 if x == "Cancellation Confirmation" else 0, IntegerType())
    
    # set churn = 1 for rows where page == 'Cancellation Confirmation'
    df = df.withColumn("churn", cancellation_event("page"))
    
    # get userId with churn == 1
    cancelled_users = df.select(['userId']).where(df.churn == 1).groupby('userId').count().toPandas()['userId'].values
    
    # create udf, which sets churn of a row to 1 if userId is in cancelled_users list
    def fill_array(userId, features):
        if(userId in cancelled_users): return 1
        else : return 0
    
    # set churn == 1 for all rows for users who cancelled their subscription
    fill_array_udf = udf(fill_array, IntegerType())
    df = df.withColumn("churn", fill_array_udf(col("userId"), col("churn")))
    
    # set column last ts with the first and the last event timestamp
    w = Window.partitionBy('userId')
    df = df.withColumn('last_ts', max('ts').over(w))
    df = df.withColumn('first_ts', min('ts').over(w))
    
    # convert timestamp to date (string)
    def get_date_from_ts(ts):
        return str(datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d'))
    
    get_date_from_ts_udf = udf(get_date_from_ts, StringType())
    df = df.withColumn('last_date', get_date_from_ts_udf(col('last_ts')))
    df = df.withColumn('first_date', get_date_from_ts_udf(col('first_ts')))
    
    # add column date and convert timetamp to date
    df = df.withColumn('date', get_date_from_ts_udf(col('ts')))
    
    # set column last_level to level when timestamp is last timestamp
    df = df.withColumn('last_level',when(df.last_ts == df.ts, df.level))
    
    # create column avg_songs to calculate average number of songs per day
    w = Window.partitionBy('userId', 'date')
    songs = df.where(df.page == 'NextSong').select('userId', 'date', count('userId').over(w).alias('songs')).distinct()
    w = Window.partitionBy('userId')
    songs = songs.withColumn('avg_songs', avg('songs').over(w))
    songs = songs.select(col("userId").alias("songs_userId"), 'avg_songs')
    songs = songs.withColumn("avg_songs", round(songs["avg_songs"], 2))
    
    # create column avg_songs to calculate average number of events per day
    w = Window.partitionBy('userId', 'date')
    events = df.select('userId', 'date', count('userId').over(w).alias('events')).distinct()
    w = Window.partitionBy('userId')
    events = events.withColumn('avg_events', avg('events').over(w))
    events = events.select(col("userId").alias("events_userId"), 'avg_events')
    events = events.withColumn("avg_events", round(events["avg_events"], 2))
    
    # calculate number of thumbs up for a user
    w = Window.partitionBy('userId')
    thumbsup = df.where(df.page == 'Thumbs Up').select('userId', count('userId').over(w).alias('thumbs_up')).distinct()
    thumbsup = thumbsup.select(col("userId").alias("thumbsup_userId"), 'thumbs_up')
    
    # calculate number of thumbs down for a user
    w = Window.partitionBy('userId')
    thumbsdown = df.where(df.page == 'Thumbs Down').select('userId', count('userId').over(w).alias('thumbs_down')).distinct()
    thumbsdown = thumbsdown.select(col("userId").alias("thumbsdown_userId"), 'thumbs_down')
    
    # calculate days since the date of the first event
    df = df.withColumn("days_active", 
              datediff(to_date(lit(datetime.now().strftime("%Y-%m-%d %H:%M"))),
                       to_date("first_date","yyyy-MM-dd")))
    
    # add column with state of the event based on location column
    def get_state(location):
        location = location.split(',')[-1].strip()
        if (len(location) > 2):
            location = location.split('-')[-1].strip()
    
        return location
    
    get_state_udf = udf(get_state, StringType())
    df = df.withColumn('state', get_state_udf(col('location')))
    
    #add column with last location of the user
    df = df.withColumn('last_state',when(df.last_ts == df.ts, df.state))
    
    # find top states
    top_states = df.select('last_state').groupBy(df.last_state).count().sort(col("count").desc()).limit(11).toPandas()
    top_states_list = top_states['last_state'][1:].values.tolist()
    
    # change names of rare states to 'OTHER'
    df = df.withColumn('last_state',when(df.last_state.isin(top_states_list), df.last_state).otherwise('OTHER'))
    
    # calculate number of add friends for a user
    w = Window.partitionBy('userId')
    addfriend = df.where(df.page == 'Add Friend').select('userId', count('userId').over(w).alias('addfriend')).distinct()
    addfriend = addfriend.select(col("userId").alias("addfriend_userId"), 'addfriend')

    # assemble everything into resulting dataset
    df_ml = df.select('userId', 'gender', 'churn', 'last_level', 'days_active', 'last_state')\
    .dropna().drop_duplicates()
    df_ml = df_ml.join(songs, df_ml.userId == songs.songs_userId).distinct()
    df_ml = df_ml.join(events, df_ml.userId == events.events_userId).distinct()
    df_ml = df_ml.join(thumbsup, df_ml.userId == thumbsup.thumbsup_userId, how='left').distinct()
    df_ml = df_ml.fillna(0, subset=['thumbs_up'])
    df_ml = df_ml.join(thumbsdown, df_ml.userId == thumbsdown.thumbsdown_userId, how='left').distinct()
    df_ml = df_ml.fillna(0, subset=['thumbs_down'])
    df_ml = df_ml.join(addfriend, df_ml.userId == addfriend.addfriend_userId, how='left').distinct()
    df_ml = df_ml.fillna(0, subset=['addfriend'])
    df_ml = df_ml.drop('songs_userId','events_userId', 'thumbsup_userId', 'thumbsdown_userId', 'addfriend_userId')
    
    return df, df_ml
    

def build_model(df_ml):
    '''
    Function builds a classification model based on the user features
    
    INPUT:
        df_ml 
        
    OUTPUT:
        model - final trained model
    '''
    
    # split into train, test and validation sets (60% - 20% - 20%)
    df_ml = df_ml.withColumnRenamed("churn", "label")

    train, test_valid = df_ml.randomSplit([0.7, 0.3], seed = 2048)
    test, validation = test_valid.randomSplit([0.5, 0.5], seed = 2048)
    
    # index and encode categorical features gender, level and state

    stringIndexerGender = StringIndexer(inputCol="gender", outputCol="genderIndex", handleInvalid = 'skip')
    stringIndexerLevel = StringIndexer(inputCol="last_level", outputCol="levelIndex", handleInvalid = 'skip')
    stringIndexerState = StringIndexer(inputCol="last_state", outputCol="stateIndex", handleInvalid = 'skip')

    encoder = OneHotEncoderEstimator(inputCols=["genderIndex", "levelIndex", "stateIndex"],
                                       outputCols=["genderVec", "levelVec", "stateVec"],
                                handleInvalid = 'keep')

    # create vector for features
    features = ['genderVec', 'levelVec', 'stateVec', 'days_active', 'avg_songs', 'avg_events', 'thumbs_up', 'thumbs_down', 'addfriend']
    assembler = VectorAssembler(inputCols=features, outputCol="rawFeatures")
    
    # normalize features
    normalizer = Normalizer(inputCol="rawFeatures", outputCol="features", p=1.0)

    # initialize random forest classifier with tuned hyperparameters
    rf = RandomForestClassifier(labelCol="label", featuresCol="features", numTrees=120, impurity = 'gini', maxDepth = 5, featureSubsetStrategy = 'sqrt')

    # assemble pipeline
    pipeline = Pipeline(stages = [stringIndexerGender, stringIndexerLevel, stringIndexerState, encoder, assembler, normalizer, rf])
    
    # fit model
    model = pipeline.fit(train)
    
    # predict churn
    pred_train = model.transform(train)
    pred_test = model.transform(test)
    pred_valid = model.transform(validation)
    
    # evaluate results
    predictionAndLabels = pred_train.rdd.map(lambda lp: (float(lp.prediction), float(lp.label)))

    # Instantiate metrics object
    metrics = MulticlassMetrics(predictionAndLabels)

    # print F1-score
    print("Train F1: %s" % metrics.fMeasure())
    
    predictionAndLabels = pred_test.rdd.map(lambda lp: (float(lp.prediction), float(lp.label)))

    # Instantiate metrics object
    metrics = MulticlassMetrics(predictionAndLabels)

    # F1 score
    print("Test F1: %s" % metrics.fMeasure())
    
    predictionAndLabels = pred_valid.rdd.map(lambda lp: (float(lp.prediction), float(lp.label)))

    # Instantiate metrics object
    metrics = MulticlassMetrics(predictionAndLabels)

    # F1 score
    print("Validation F1: %s" % metrics.fMeasure())
    
    return model

def save_model(sc, model, model_filepath):
    '''
    Function saves trained model
    
    INPUTS:
        1. spark contect from above
        2. model - model name
        3. model_filepath - file path to save model to
    '''
    model.save(model_filepath)

def main():
    # read parameters
    if len(sys.argv) == 3:
        data_filepath, model_filepath = sys.argv[1:]
        
        # load data
        print('Loading data...\n')
        sc, df = load_data(data_filepath)
          
        # clean data and prepare dataset for machine learning
        print('Processing data... \n')
        df, df_ml = prepare_dataset(df)
               
        # build machine learning model
        print('Building mode... \n')
        model = build_model(df_ml)
        
        # save model
        print('Saving model... \n')
        save_model(sc, model, model_filepath)
        
        print('Training Complete. \n')

    else:
        print('Give data filepath as argument one and the path to save the resulting mdoel as argment two.'\
                'Example: python train_classifier.py ../data/sparkify.csv classifier')


if __name__ == '__main__':
    main()
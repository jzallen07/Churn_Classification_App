import os
import sys

# Path for spark source folder
os.environ['SPARK_HOME']="/Users/zack.allen/.pyenv/versions/3.6.5/envs/venv/lib/python3.6/site-packages/pyspark"

# Append pyspark  to Python Path
#sys.path.append("/Users/zack.allen/.pyenv/versions/3.6.5/envs/venv/lib/python3.6/site-packages/pyspark")

try:
    from pyspark import SparkContext
    from pyspark import SparkConf
    print ("Successfully imported Spark Modules")

except ImportError as e:
    print ("Can not import Spark Modules", e)
    sys.exit(1)



    # export SPARK_HOME="/Users/zack.allen/.pyenv/versions/3.6.5/envs/venv/lib/python3.6/site-packages/pyspark"
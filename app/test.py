import os
import sys

# Path for spark source folder
os.environ['SPARK_HOME']=""

try:
    from pyspark import SparkContext
    from pyspark import SparkConf
    print ("Successfully imported Spark Modules")

except ImportError as e:
    print ("Can not import Spark Modules", e)
    sys.exit(1)



    # export SPARK_HOME=""
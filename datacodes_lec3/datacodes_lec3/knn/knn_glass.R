
# 清除当前的环境
rm(list = ls())


library(MASS)
library(FNN)

# loads the data into R
data(fgl) 

View(fgl)

# The data has six types of glasses
summary(fgl$type)

#the scale function centers and scales the columns to have 0 mean and sd of 1

x <- scale(fgl[,1:9]) # column 10 is the class label

#calculates the mean of each column (2 indicates columns) of the scaled data `x'`
apply(x,2,mean)

#calculates the sd of each column (2 indicates columns) of the scaled data `x'`
apply(x,2,sd)

set.seed(100)
# randomly select 10 obs from 214 obs to be the test data
test <- sample(1:214, 10)

nearest1_test <- knn(train=x[-test, ], test = x[test, ], cl = fgl$type[-test], k=1)
nearest5_test <- knn(train=x[-test, ], test = x[test, ], cl = fgl$type[-test], k=5)

type_test <- fgl$type[test]

View(data.frame(type_test, nearest1_test,nearest5_test))


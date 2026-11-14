rm(list=ls())
## SVM for Multiclass Classification with MNIST Data



#"tdarec" is an R package that contains two subsets of the MNIST database with handwritten digits from 0 to 9
#mnist_train contains 600 instances of handwritten digits, with $digit reflecting the pixel values (integers in the range 0-255) in a 28 X 28 matrix, and $label showing the digit in a factor 
#mnist_test contains 100 instances of handwritten digits for testing

install.packages("tdarec")
library(tdarec)
data(mnist)

#install the "mnist" package, which contains the mnist data set


data(mnist)

train_x <- as.data.frame(do.call(rbind, lapply(mnist_train$digit, as.vector)))
train_y <- mnist_train$label
test_x <- as.data.frame(do.call(rbind, lapply(mnist_test$digit, as.vector)))
test_y <- mnist_test$label


dim(train_x)
str(train_x)
prop.table(table(train_y))

digit <- t(apply(matrix(as.numeric(train_x[3,]),nrow = 28),2,rev)) #look at one digit
image(digit, col = grey.colors(255))

#select all training samples with y = 8
train_x8 <- train_x[train_y==8,]

#look at the first 9 samples of 8 
par(mfrow=c(3,3))
par(mar=c(2,2,2,2))
for (i in 1:9){
  digit <- t(apply(matrix(as.numeric(train_x8[i,]),nrow=28),2,rev)) #look at one digit
  image(digit, col = grey.colors(255))
}
par(mfrow=c(1,1))

install.packages("e1071")
library(e1071)
train_data <- data.frame(y=as.factor(train_y),train_x)

fit <- svm(y~., data=train_data, kernel="linear", cost=10)
pred <- predict(fit,test_x)
(table <- table(Predicted=pred,Actual=test_y))
(accuracy <- sum(diag(table))/sum(table))

fit <- svm(y~., data=train_data, kernel="polynomial",degree=2, gamma=0.02, cost=10)
pred <- predict(fit,test_x)
(table <- table(Predicted=pred,Actual=test_y))
(accuracy <- sum(diag(table))/sum(table))

fit <- svm(y~., data=train_data, kernel="polynomial",degree=3, gamma=0.02, cost=10)
pred <- predict(fit,test_x)
(table <- table(Predicted=pred,Actual=test_y))
(accuracy <- sum(diag(table))/sum(table))


# clear environment
rm(list = ls())

#load the working environment, which contains a list with 5 elements

# Run from the MLEC repository root; teaching example only.
load("data/archive/course_examples/lecture03/knn/mixture.RData")


#check the structure of the list "mixture"
str(mixture)

x <- mixture$x
y <- mixture$y
px1 <- mixture$px1
px2 <- mixture$px2
xnew <- mixture$xnew 

# x is 200 X 2 matrix containing the training data covariates x1 and x2
print(x)
# y is a 100 X 1 vector containing the training data response variable y
print(y)
#px1 vector has 69 values, ranging from -2.6 to 4.2 in an interval of 0.1 
summary(px1)

#px2 vector has 99 values, ranging from -2.00 to 2.90 in an interval of 0.05
summary(px2)

#x_new is a matrix with 69 rows and 99 columns (6831 cells) with all interactions btw px1 and px2, which is used as training data 
print(xnew)

#load the library FNN
library(FNN)

#below, we plot the knn decision boundary when k=1, 7, 15, and 60. 



#set a 2x2 grid for plots 
par(mfrow=c(2,2))

#set all margins for the plots to 2 
par(mar=c(2,2,2,2))

#loop over four different values of k: 1, 7, 15, and 60 
for (k in c(1,7,15,60)){
  #Perform k-nearest neighbor classification using the training data x and y, and test data xnew
  fit <- knn(x, xnew, y, k=k, prob=TRUE)
  #save the predicted "probability" for the WINNING class as vote (note that when predicted class is y=0, the winning class is y=0)
  vote <- attr(fit, "prob")
  #convert vote to the "probability" of class y=1  
  prob <- ifelse(fit=="1", vote, 1-vote)
  #with test data xnew, prob is vector with 6831 values
  #reshape prob to a 69 x 99 matrix
  prob <- matrix(prob, length(px1), length(px2))
  #draw a contour plot at the 0.5 probability level (the decision boundary) for the grid of points in the test data.
  contour(px1, px2, prob, levels=0.5, labels="", xlab="", ylab="", main=
            paste(k,"-nearest neighbor"), axes=FALSE)
  #plot the points in the training data, using different colors for y=0 and y=1 class
  points(x, col=ifelse(y==1,1,4))
  #plot all the points in the test data
  grid <- expand.grid(x=px1, y=px2)
  points(grid, pch=".", cex=1.2, col=ifelse(prob>0.5,"grey","blue"))
  #draw a box for each panel
  box()
}






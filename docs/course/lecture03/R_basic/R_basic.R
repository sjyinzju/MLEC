
# 清除当前的环境
rm(list = ls())

# 1. 基础数据结构与运算

# 1.1 基础数据结构

#数值型

# "<-"”" 为赋值符号，其含义是将后面的内容赋值给符号前面的变量
a <- 10.5      # 浮点数
class(a)       # 输出: "numeric"
b <- 5         # 整数也被存储为数值型
class(b)       # 输出: "numeric"
c <- 5L        # 整数型
class(c)       # 输出: "integer"
d <- 3 + 2i    # 复数
class(d)       # 输出: "complex"


#逻辑型

e <- TRUE      # 逻辑型
f <- FALSE     # 逻辑型
class(e)       # 输出: "logical"

#因子型：表示分类数据的特殊数据类型
#可以是有序的或无序的
i <- factor(c("男", "女", "男", "男", "女"))
class(i)       # 输出: "factor"
levels(i)      # 输出: "女" "男"

#字符型（character）用于表示文本。
#在R中，字符串需要用单引号或双引号括起来
g <- "Hello"    # 字符型
h <- "世界"     # 字符型，支持Unicode字符
class(g)       # 输出: "character"
print(h)      # 显示: "世界"

#缺失值
#当一个元素或者取值在调查中无法取得时，相关的位置会保留一个专门NA（not avaiable）取值。对NA的任何运算结果都是NA。

x <- c(1, 2, NA, 4) #NA表示缺失值

print(x)

# 1.2 数据类型的检测与转换
x <- 5
is.numeric(x)  # 输出: TRUE
is.integer(x)  # 输出: FALSE（因为x是numeric而非integer）
y <- "Hello"
is.character(y) # 输出: TRUE
z <- factor(c("红", "绿", "蓝"))
is.factor(z)   # 输出: TRUE
w <- "123"
is.character(w) # 输出: TRUE
is.numeric(w) # 输出: FALSE
w <- as.numeric(w)  # 输出: 123（字符串转为数值）
is.numeric(w) # 输出: TRUE
v <- 1
v <- as.logical(v)  # 输出: TRUE（非零数值转为TRUE）
u <- TRUE
as.numeric(u)  # 输出: 1（TRUE转为1，FALSE转为0）
t <- c(1, 2, 3)
t <- as.character(t) # 输出: "1" "2" "3"（数值向量转为字符向量）

# 1.3 变量与赋值
x <- 3.14159
get("x")         # 提取名为x的变量值
assign("y", 42)  # 将值42赋给变量y

# 1.4运算符与运算

3 + 5       # 8
6 / 2       # 3
2^3         # 8
sqrt(16)    # 4
5 > 3       # TRUE
5 == 3      # FALSE
5 != 3      # TRUE
a <- TRUE; b <- FALSE
a & b       # FALSE (逻辑与)
a | b       # TRUE  (逻辑或)
!a          # FALSE (逻辑非)
7 %/% 3     # 2  (整数除法)
7 %% 3      # 1  (取余)


# 2. 数据结构

# 2.1 向量

v1 <- c(1, 2, 3, 4, 5) # 创建数值型向量
v2 <- c("a", "b", "c") # 创建字符型向量
v3 <- c(TRUE, FALSE, TRUE) # 创建逻辑型向量
v4 <- 1:5 # 使用冒号操作符创建序列 1 2 3 4 5
v5 <- 2*1:5 #生成 2 4 6 8 10


# 函数seq()可以产生有规律的各种序
# 这一函数的句法是seq(from, to, by)
# from表示序列的起始值，to表示序列的终止值，by表示步长
# 当参数by缺省时，默认步长为1。

v6 <- seq(1, 10, 2) # 使用seq函数创建等差序列 1 3 5 7 9

# 函数rep()可以用各种复杂的形式获得重复的对象，其句法是rep(x,times, ...)，
# 其中x为要重复的对象，而times表示重复的次数。

v7 <- rep(c(1, 2), 3) #将向量c(1, 2)重复3次
print(v7)

# 向量索引方法。取出向量x的第i个元素可以用x[i]来实现

v6[2] #输出v6中的第二个数，即3
v6[2] <- 5 #将v6中的第二个数从3换为5
v6[1:3] #输出 1 5 5 

# 2.2 矩阵

m <- matrix(1:9, nrow = 3, ncol = 3) # 创建3*3矩阵

rownames(m) <- c("row1", "row2", "row3")# 对行名赋值
colnames(m) <- c("col1", "col2", "col3") # 对列名赋值
m[1, 2]        # 第1行第2列元素
m[1, ]         # 第1行所有元素
m[, 2]         # 第2列所有元素

# 2.3 列表

# 创建列表
listdata <- list(
  univ = "浙江大学", 
  startyear = 1897L, 
  position = c(120.085, 30.303)
) 

# 代码中的listdata包含univ、staryear和position三个分量
# 这三个分量分别是字符、数值和经纬度所组成的数值向量

# [...]得到的是列表中的一个子列表，包含分量名称

listdata$univ

listdata[1] #输出 $univ [1] "浙江大学"

# [[...]] 得到的是列表中的一个子列表中的元素，不包含分量名称

listdata[[1]] #输出 [1] "浙江大学"

# 2.4 数据框

# 创建数据框
df <- data.frame(
  name = c("张三", "李四", "王五"),
  age = c(25, 30, 35),
  height = c(175, 180, 168)
)
df[1, 2]         # 第1行第2列的元素
df[1, ]         # 第1行的所有元素
df$name         # 访问name列
df[, "name"]     # 访问name列
df[df$age > 25, ] # 访问年龄大于25的观测

df[df$age > 25, "height"] # 访问年龄大于25的观测

# 3 控制语句与函数

# 3.1 控制语句

# if-else语句
a <-  1
ifelse(a == 1, "Right", "Wrong") # 返回 Right

# switch 
n <- 2
switch(n, "公共管理", "经济学", "数学")  # 返回 "经济学"

# 基本for循环
j <- 0
for (i in 1:5) {
  j <- j + i 
}
print(j) #输出 15

# while循环示例
counter <- 1
total <- 0
while (counter <= 5) {
  total <- total + counter
  counter <- counter + 1
}
print(total)  # 输出 15

#repeat循环示例
counter <- 1
repeat {
  print(counter)
  counter <- counter + 1
  if (counter > 5) {
    break
  }
}
# break示例

for (i in 1:10) {
  if (i > 5) {
    break  # 当i大于5时，跳出循环
  }
  print(i)
}

# next示例
for (i in 1:10) {
  if (i %% 2 == 0) {
    next  # 当i是偶数时，跳过当前迭代
  }
  print(i)
}

# 3.2 自定义函数

# 定义计算GDP增长率的函数
gdpgrowth <- function(current, previous, percent = TRUE) {
  # 参数验证
  if (!is.numeric(current) |!is.numeric(previous)) {
    stop("GDP values must be numeric")
  }
  if (previous <= 0) {
    stop("Previous GDP must be positive")
  }
  # 计算增长率
  growthrate <- (current - previous) / previous
  # 根据percent参数决定是否转换为百分比
  if (percent) {
    growthrate <- growthrate * 100
  }
  return(growthrate)
}
# 使用函数
gdpgrowth(105, 100)  # 输出: 5（百分比形式）
gdpgrowth(105, 100, percent = FALSE)  # 输出: 0.05（小数形式）


# 4. Use Machine Learning to Predict Property Value

# Install the “MASS” package, add the Boston data set, and load the relevant
#packages needed
install.packages(c('MASS', 'gamlr', 'tree', 'randomForest', 'gbm'))
library(MASS)
library(gamlr)
library(tree)
library(randomForest)
library(gbm)

rm(list=ls()) 

data(Boston)
# （2）Obtain the row and column sizes, display the first five rows,
#, and call ``help()'' to understand every variable.
dim(Boston)
head(Boston, 5)

names(Boston)
help(Bonston)
class(Boston)

#（3）Set the seed value at 123456
#randomly select 80% of the sample as the training set
#the remaining sample as the test data.
set.seed(123456)
size <- sample.int(506, 506*0.8)
train <- Boston[size, ]
test <- Boston[-size, ]


#*******************************************  
#                CV_lasso                  *
#*******************************************

#Construct training set and test set
# train[,-14] means excluding column 14
X_train <- as.matrix(train[,-14] )
class(X_train)
y_train <- train$medv  

X_test <- as.matrix(test[, -14]) 
y_test <-  test$medv 

## CV lasso 
medv_cvlasso <- cv.gamlr(X_train, y_train, family = "gaussian", verb = TRUE, nfold = 10)
plot(medv_cvlasso, bty="n")

## CV-min rule
cvlasso.min <- coef(medv_cvlasso, select = "min")
## Show the log value of lambda selected by the CV-min rule 
log(medv_cvlasso$lambda.min)
## Under the CV-min rule, 12 variables are selected
sum(cvlasso.min != 0) 

## CV-1se rule
cvlasso.1se <- coef(medv_cvlasso, select = "1se")
## Show the log value of lambda selected by the CV-min rule 
log(medv_cvlasso$lambda.1se)
## If we instead using the 1se rule, only 8 variables are selected
sum(cvlasso.1se != 0) 


#*******************************************  
#               Regression Tree            *
#*******************************************  

## Fit a regression tree to predict the housing price. 
#Draw the tree constructed.
#How many terminal nodes are in this tree?

medv_tree <- tree(medv ~ ., data = train, mincut=1)
summary(medv_tree)

par(mfrow=c(1,1))
plot(medv_tree)
text(medv_tree, digits=2)



#*******************************************  
#              Random Forest               *
#*******************************************  

# Train a random forest with 1,000 regression trees to predict the housing price. During the construction of each tree
#instead of looking for the best condition over all available features
#only use a random subset of 2/3 features at each node.

medv_rf <- randomForest(medv ~ ., data = train, replace = TRUE, mtry = 2/3 * 13,
                        ntree = 1000, nodesize = 10, importance = TRUE)

importance(medv_rf)
varImpPlot(medv_rf, main = "Variance Importment Plot")

#*******************************************  
#              Gradient Boosting           *
#*******************************************  

medv_gbm <- gbm(
  formula = medv ~ ., 
  data = train, 
  distribution = "gaussian", 
  n.trees = 500, 
  interaction.depth = 4, 
  shrinkage = 0.01, 
  cv.folds = 10
)


#**********************************************
#      Out-of-sample (OOS) Prediction *********
#**********************************************

#Switch to the test set, apply the four models constructed in (a), (b), (c), (d) --- namely the cut-off model, the Lasso model, the regression tree after pruning, and the random forest --- to predict the housing price (``medv'') and calculate the out-of-sample $R^2$ for the four models. 
#Rank these four models in terms of the out-of-sample performance in prediction. 


# Define a function to calculate the OOS R^2 
calculate_r_squared <- function(actual, predicted) {
  rss <- sum((actual - predicted)^2)
  tss <- sum((actual - mean(actual))^2)
  r_squared <- 1 - rss / tss
  return(r_squared)
}

#OOS Predictions

pred_cvlasso <- predict(medv_cvlasso, X_test,lambda=med_cvlasso$lambda.min)

pred_tree <- predict(medv_tree, newdata = as.data.frame(X_test))

pred_rf <- predict(medv_rf, newdata = as.data.frame(X_test))

pred_gbm <- predict(medv_gbm, newdata = as.data.frame(X_test), n.trees = medv_gbm$n.trees)

# 计算每个模型的外样本R^2
oos_r2 <- vector()
oos_r2['cv-lasso'] <- calculate_r_squared(y_test, pred_cvlasso)
oos_r2['reg-tree']<- calculate_r_squared(y_test, pred_tree)
oos_r2['rf']<- calculate_r_squared(y_test, pred_rf)
oos_r2['gbm']<-calculate_r_squared(y_test, pred_gbm)

sort(oos_r2)


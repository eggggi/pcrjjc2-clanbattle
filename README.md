# 基于pcrjjc2的会战推送插件

**本项目基于AGPL v3协议开源**

现在应该能根据时间正确判断出刀类型了(把boss打残了就能看到后面的色图了，这算不算某种程度的脱衣<--自己在310张卡面里面塞了35张脱衣卡面，抽卡色图什么的弱爆了
## 配置方法

1. 打开hoshino插件文件夹
2. git clone https://github.com/AddOneSecondL/pcrjjc2-clanbattle.git
3. __init__.py 第32行改成需要推送的群
4. config文件里面添加pcrjjc2-clanbattle
5. account.json填上在会里的号的账号密码
6. 发送会战状态可以查看当前会战状态
7. 会战前一天请清空output.txt并输入初始化会战推送
8. 会战期间输入 切换会战推送 来打开/关闭推送，默认关闭
9. 关于查档线功能，结算时不能获取数据，官方结算完和会战开启时可以使用，通过获取游戏内数据，输入 查档线 可以查看各档档线，输入 查档线 1,2,3,4 可以查看 1,2,3,4 名详情，其他名次也是这样
10. 查档线新增一种按名字查询的方法， 查档线 行会名，会列出部分符合条件的行会

自用改的渣代码，见谅



要做的事：
1.优化图片排版
2.自动获取会战日期(应该找个日历源就行，游戏内可以但是需要登陆
3.获取当期BOSS头像(不知道下期bossid上哪找
4.想到了再改吧

最终看起来应该是这样子的
![](example/1.jpg)

![](example/2.png)

查档线
![](example/3.png)

## 开发环境

环境依赖: Python3.8

IDE推荐: python使用pyCharm

项目启动
```
Step1: 安装python依赖包 pip3 install -r requirements.txt

Step2: 修改/config/config.ini文件中Platform->url为后端地址

Step3: 修改/config/config.ini文件中Provider->host为本机IP

Step4: 修改/config/config.ini文件中StartParam是否启用安卓/苹果设备挂载

Step5: 如挂载苹果设备 win电脑需要安装iTunes 且手机预安装WDA并填写wda-bundle-id

Step6: owner填写平台用户账号和project填写项目名 默认system为所有项目所有人共享设备

Step7: 电脑usb连接手机后 启动代理 python3 startup.py
```

验证启动

平台设备管理查看自己的设备，显示在线，证明启动成功。
注意: 
```
① 本地挂载的设备仅限同一网络下的人或引擎可以在线操作执行测试, 其他网络的人或引擎无法使用
② 如同网络下无法使用，请检查挂载设备的电脑是否开启防火墙
③ 如需跨网段使用，可以设置网络反向代理或给主机添加公网IP，具体情况找自家IT解决
```

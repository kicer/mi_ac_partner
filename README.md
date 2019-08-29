# 米家网关收音机home-assistant插件
Fork from [@vonzeng "更新v0.04：米家网关、空调伴侣收音机功能插件"](https://bbs.hassbian.com/thread-6934-1-1.html)

### Usage
```
media_player:
  - platform: mi_ac_partner
    name: '收音机'
    host: '192.168.x.x'
    token: 'xxx'
```

1. 插件路径: ~/.homeassistant/custom_components/mi_ac_partner/
2. 暂不支持设备搜索，host须设置。
3. token可通过米家app获取。

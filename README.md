# 米家网关收音机homeassistant插件
Fork from (@vonzeng)[https://bbs.hassbian.com/forum.php?mod=viewthread&tid=6934]

### Usage
```
media_player:
  - platform: mi_ac_partner
    name: '收音机'
    host: '192.168.x.x'
    token: 'xxx'
```

1. 插件路径: ~/.homeassistant/custom_components/mi_ac_partner/media_player.py
2. 暂不支持设备搜索，host须设置。
3. token可通过米家app获取。

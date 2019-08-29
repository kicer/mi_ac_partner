'''
版本：v0.04
修改内容：
1.修改了匹配不到电台名时的提示内容。出现该情况，更大的可能是你之前收藏的电台已（临时）失效。请到
    app内确认该电台是否还有效，失效则删除，也可保留着（也许一会又有效了）。
2.解决app里收音机收藏的电台数量超过10个时的错误，已改成能支持最多30个电台了。若收藏超过30个电台，
    也实在没意义了，建议你删掉一些吧。-:)
3.解决爬虫网页时某一类别电台总数变化为零时而出现的错误，或新增电台类别时而没能及时获取；
4.启动HA后，若收音机不在播放状态时，media_player的默认状态改为为turn_off，而非之前默认的paused，
    于减少不必要的自动定时miio查询状态；
5.修正当电台的节目名不存在时出现的判断语句错误；
6.优化代码，尽量减少不必要的miio查询；
7.修改了爬虫网页电台总表、选择电台列表的更新机制，自动更新周期调整为15分钟；
8.当你需要手动更新电台总清单（适用于当网上电台清单有变化时，或HA启动时刚好没有节目名）、选择电台
    列表（适用于当你在app里添加、删除电台后）时，可通过对播放器的重新turn on来实现强制更新。
9.解决了当你在app里没收藏电台就直接播放时出现的错误；
10.规范了变量的命名，提高代码的可读性；



使用说明：
1.适用于HA0.88之后的版本，之前的版本需修改文件名和所在目录名；
2.通过app在收音机至少先收藏一个电台；
3.只在lumi.gateway.v3、lumi.acpartner.v3两款网关上测试过；
4.配置文件里添加：
media_player:
  - platform: mi_ac_partner
    name: 
    host: 
    token: 

5.将本文件media_player.py放到：../custom_components/mi_ac_partner/目录下。
6.重启Home Assistant。

von(vaughan.zeng@gmail.com)
'''
import asyncio,aiohttp,json
from homeassistant.util import Throttle

import logging
import voluptuous as vol
import datetime
import urllib.request

from homeassistant.const import (CONF_NAME, CONF_HOST, CONF_TOKEN,
    STATE_PAUSED, STATE_PLAYING, STATE_OFF)
from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA)
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC, MEDIA_TYPE_PLAYLIST, SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE, SUPPORT_PLAY, SUPPORT_PLAY_MEDIA, SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE, SUPPORT_VOLUME_SET, SUPPORT_TURN_OFF, SUPPORT_TURN_ON)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Xiaomi AC Partner'
ICON = 'mdi:radio'

# SCAN_INTERVAL = datetime.timedelta(seconds=50)
UPDATE_STATION_LIST = datetime.timedelta(minutes=15)

SUPPORT_XIAOMIACPARTNER = SUPPORT_VOLUME_SET | SUPPORT_PAUSE | SUPPORT_PLAY |\
    SUPPORT_NEXT_TRACK | SUPPORT_PREVIOUS_TRACK | SUPPORT_SELECT_SOURCE | \
    SUPPORT_TURN_ON | SUPPORT_TURN_OFF

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_TOKEN): vol.All(str, vol.Length(min=32, max=32)),
}, extra=vol.ALLOW_EXTRA)


async def async_setup_platform(hass, config, async_add_devices, discovery_info = None):
    # from miio import Device, DeviceException
    from miio import Device, DeviceException
    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    token = config.get(CONF_TOKEN)

    _LOGGER.info('%s（网关）初始化......',name)

    midevice = Device(host, token)
    model = midevice.info().model
    acPartner = XiaomiacPartner(midevice, name, model)

    async_add_devices([acPartner], True)


class XiaomiacPartner(MediaPlayerDevice):
    """Representation of a Spotify controller."""
    def __init__(self, midevice, name, model):
        """Initialize."""
        self._midevice = midevice
        self._name = name
        self._state = None
        self._current_station_name = None
        self._volume = None
        self._image_url = None
        self._programname = None
        self._current_station_id = None
        self._current_selected_station = None
        self._source_list = []
        self._app_name = model

        self._get_prop = False
        self._virtual_off = True
        self._station_list_total = None
        self._favorites_station_list = None


    async def async_update(self):
        """Update state and attributes."""
        await self.async_station_list_total()
        await self.async_generate_station_selection_list()

        if self._get_prop:
            await asyncio.sleep(2)
            self._get_prop = False

        # Get current station id, volume, status
        status = self._midevice.send("get_prop_fm", [])
        self._current_station_id = status["current_program"]
        self._volume = int(status['current_volume']) / 100
        current_status = status['current_status']

        # Current radio status
        if current_status == 'run':
            self._virtual_off = False
            self._state = STATE_PLAYING
        else:
            self._state = STATE_PAUSED

        if self._virtual_off and current_status != 'run':
            self._state = STATE_OFF

        # Current station name, image url, program name, selected station
        current_station_dict = await self.async_station_list_total_index(self._current_station_id)
        if current_station_dict == None:
            self._image_url = None
            self._programname = None
            self._current_station_name = str(self._current_station_id) + ' ' + '此电台当前失效，请到app内确认！'
            self._current_selected_station = None
        else:
            self._image_url = current_station_dict['coverLarge']
            self._current_station_name = current_station_dict['name']
            self._current_selected_station = str(self._current_station_id) + ' ' + self._current_station_name
            if 'programName' not in current_station_dict:
                self._programname = '没有当前节目名'
                _LOGGER.warning('%s（网关）的%s电台没有当前节目名。',self._name, self._current_selected_station)
            else:
                self._programname = current_station_dict['programName']

    @property
    def name(self):
        """Return the name."""
        return self._name

    @property
    def icon(self):
        """Return the icon."""
        return ICON

    @property
    def state(self):
        """Return the playback state."""
        return self._state

    @property
    def volume_level(self):
        """Return the device volume."""
        return self._volume

    @property
    def source_list(self):
        """Return a list of source devices."""
        if self._source_list:
            return list(self._source_list)

    @property
    def source(self):
        """Return the current playback device."""
        return self._current_selected_station

    @property
    def media_artist(self):
        """Return the artist of current playing media (Music track only)."""
        return self._current_station_name

    @property
    def media_title(self):
        """Return the media title."""
        return self._programname

    @property
    def media_track(self):
        """Return the track number of current media (Music track only)."""
        return self._current_station_id

    @property
    def media_image_url(self):
        """Return the image url of current playing media."""
        return self._image_url

    @property
    def app_name(self):
        """Return the current running application."""
        return self._app_name

    @property
    def supported_features(self):
        """Return the media player features that are supported."""
        return SUPPORT_XIAOMIACPARTNER

    @property
    def media_content_type(self):
        """Return the media type."""
        return MEDIA_TYPE_MUSIC

    async def _fetch(self, url):
        timeout = aiohttp.ClientTimeout(total=2) # 获取列表时最大10s超时
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                content = await response.text()
                data = json.loads(content)
                if data['data']['totalSize'] > 0:
                    return data['data']['data']

    # 爬虫抓取网页上电台总清单
    @Throttle(UPDATE_STATION_LIST)
    async def async_station_list_total(self):
        station_list_total = []
        try:
            for idx in range(1,20):
                url = 'http://live.ximalaya.com/live-web/v2/radio/category?categoryId=%s&pageNum=1&pageSize=300' % idx
                station_list = await self._fetch(url)
                _LOGGER.info('%s（网关） load radio list>%s',self._name,idx)
                if station_list:
                    station_list_total = station_list_total + station_list
        except:
            pass
        self._station_list_total = station_list_total

    # 查询空调伴侣（网关）收音机的收藏电台清单
    async def async_favorites_station_list(self):
        # Availabel Radio favorites stations list (max = 30)
        chs0 = []
        chs1 = []
        chs2 = []
        channels = self._midevice.send("get_channels", {"start": 0})
        if channels:
            chs0 = channels["chs"]
            if len(chs0) == 10:
                channels = self._midevice.send("get_channels", {"start": 10})
                if channels:
                    chs1 = channels["chs"]
                    if len(chs1) == 10:
                        channels = self._midevice.send("get_channels", {"start": 20})
                        if channels:
                            chs2 = channels["chs"]
        else:
            _LOGGER.error('%s（网关）中没有收藏的电台。请先到app里收藏至少一个电台，然后重启HA。',self._name)
        favorites_station_list = chs0 + chs1 + chs2
        self._favorites_station_list = favorites_station_list
        return favorites_station_list

    # 生成media_player上电台选择列表
    @Throttle(UPDATE_STATION_LIST)
    async def async_generate_station_selection_list(self):
        favorites_station_list = await self.async_favorites_station_list()
        station_selection_list = []
        list_count = len(favorites_station_list)
        x = 0
        while x <= list_count - 1:
            favorites_station_id = favorites_station_list[x]['id']
            favorites_station_dict = await self.async_station_list_total_index(favorites_station_id)
            if favorites_station_dict == None:
                favorites_station_name = str(favorites_station_list[x]['id']) + ' ' + '此电台当前失效，请到app内确认！'
                _LOGGER.warning('%s（网关）中收藏的电台（代码：%s）当前不在自动生成的电台总表中，此电台可能已（临时）失效，请到app内确认。',self._name,favorites_station_list[x]['id'])
            else:
                favorites_station_name = str(favorites_station_list[x]['id']) + ' ' + favorites_station_dict['name']
            x +=1
            station_selection_list.append(favorites_station_name)
        self._source_list = station_selection_list

    async def async_station_list_total_index(self, key):
        for idx, val in enumerate(self._station_list_total):
            if val['id'] == key:
                station_name_dict = self._station_list_total[idx]
                return station_name_dict

    async def async_set_volume_level(self, volume):
        """Set the volume level."""
        self._midevice.send('volume_ctrl_fm',[str(volume * 100)])
        self._get_prop = True

    async def async_media_next_track(self):
        """Skip to next track."""
        await self.async_radio_index('next')
        self._get_prop = True

    async def async_media_previous_track(self):
        """Skip to previous track."""
        await self.async_radio_index('previous')
        self._get_prop = True

    async def async_radio_index(self, key):
        if len(self._favorites_station_list) < 1:
            _LOGGER.warning('%s（网关）请先在米家app端收藏至少一个电台！',self._name)
            return False
        try:
            for idx, val in enumerate(self._favorites_station_list):
                if val["id"] == self._current_station_id:
                    current_index = idx
                    break
            if key == 'next':
                if current_index >= len(self._favorites_station_list) - 1:
                    current_index = 0
                else:
                    current_index += 1
            elif key == 'previous':
                if current_index == 0:
                    current_index = len(self._favorites_station_list) - 1
                else:
                    current_index -= 1
        except UnboundLocalError:
            _LOGGER.warning('%s（网关）当前播放电台不在电台选择列表中（在app中没有被收藏），换台直接跳到列表中的第一个。',self._name)
            current_index = 0

        channel = self._favorites_station_list[current_index]
        self._midevice.send("play_specify_fm", {'id': channel["id"], 'type': 0})

    async def async_media_play(self):
        """Start or resume playback."""
        self._midevice.send('play_fm',["on"])
        self._get_prop = True

    async def async_media_pause(self):
        """Pause playback."""
        self._midevice.send('play_fm',["off"])

    async def async_turn_on(self):
        """Turn the media player on."""
        await self.async_station_list_total()
        await self.async_generate_station_selection_list()
        self._midevice.send('play_fm',["on"])
        self._virtual_off = False
        self._get_prop = True

    async def async_turn_off(self):
        """Turn the media player off."""
        self._midevice.send('play_fm',["off"])
        self._virtual_off = True

    async def async_select_source(self, source):
        """Select playback device."""
        for i in range(len(self._source_list)):
            if source in self._source_list[i]:
                code = self._source_list[i].split(' ',1)[0]
                break

        self._midevice.send("play_specify_fm", {'id': int(code), 'type': 0})
        self._get_prop = True


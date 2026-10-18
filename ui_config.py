"""Small, local UI preference file. Never stores game traffic or character names."""
import json
import os
from pathlib import Path

DEFAULTS = {'hud_visible': True, 'hud_opacity': 88, 'hud_scale': 100,
            'hud_clickthrough': False, 'sound_sensitivity': 75,
            'hud_x': None, 'hud_y': None, 'radar_mode': 'Auto',
            'network_backend': 'Working radar',
            'audio_hud_visible': True, 'audio_hud_opacity': 88, 'audio_hud_scale': 100,
            'audio_hud_clickthrough': False, 'audio_hud_x': None, 'audio_hud_y': None,
            'network_alert_enabled': True, 'sound_detection_enabled': True,
            'glow_detection_enabled': True}


def config_path():
    directory = os.getenv('LOCALAPPDATA')
    return (Path(directory) if directory else Path.home()/'.config')/'Aion2CubeFinder'/'ui_settings.json'


def load(path=None):
    conf=dict(DEFAULTS)
    try:
        data=json.loads(Path(path or config_path()).read_text(encoding='utf-8'))
        if not isinstance(data,dict):return conf
        conf.update({k:data[k] for k in DEFAULTS if k in data})
    except (OSError, ValueError, UnicodeError):pass
    for name,lo,hi in [('hud_opacity',45,100),('hud_scale',70,150),('audio_hud_opacity',45,100),('audio_hud_scale',70,150),('sound_sensitivity',0,100)]:
        try:conf[name]=max(lo,min(hi,int(conf[name])))
        except (ValueError,TypeError):conf[name]=DEFAULTS[name]
    for k in ('hud_visible','hud_clickthrough','audio_hud_visible','audio_hud_clickthrough',
              'network_alert_enabled','sound_detection_enabled','glow_detection_enabled'):
        if not isinstance(conf[k], bool):conf[k]=DEFAULTS[k]
    if conf['radar_mode'] not in ('Auto','World','Screen'):conf['radar_mode']='Auto'
    if conf['network_backend'] not in ('Working radar','Experimental v12'):
        conf['network_backend']='Working radar'
    return conf


def save(value,path=None):
    target=Path(path or config_path())
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.tmp')
    clean={k:value.get(k,DEFAULTS[k]) for k in DEFAULTS}
    temporary.write_text(json.dumps(clean,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,target)
    return target

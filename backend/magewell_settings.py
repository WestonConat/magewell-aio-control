# magewell_settings.py

def get_modified_settings(magewell_id: str) -> dict:
    return {
        "is-low-latency": 0,
        "is-auto-send-file": 0,
        "is-auto-del-file": 0,
        "is-check-update": 0,
        "audio-sync-offset": 0,
        "enable-advanced-pcr": 0,
        "udp-mtu": 1496,
        "cloud-num": 2,
        "enable-ndi-hx3": 0,
        "enable-4k60-input": 0,
        "enable-usb-audio-capture": 1,
        "net-prior": 1,
        "input-source": {
            "source": 2,
            "mixer": {
                "input-device": 2,
                "is-hdmi-top": 0,
                "type": 0,
                "location": 2
            }
        },
        "use-nosignal-file": 1,
        "nosignal-files": [
            {"id": 0, "is-use": 0, "is-edit": 0, "file-path": "/no-signal/default0.jpg", "time": 0},
            {"id": 1, "is-use": 0, "is-edit": 0, "file-path": "/no-signal/default1.jpg", "time": 0},
            {"id": 2, "is-use": 1, "is-edit": 1, "file-path": "/no-signal/default2.jpg", "time": 17149641665160202}
        ],
        "video-input-format": {
            "hdmi": {"is-color-fmt": 0, "color-fmt": 1, "is-quant-range": 0, "quant-range": 1},
            "sdi": {"is-color-fmt": 0, "color-fmt": 1, "is-quant-range": 0, "quant-range": 1}
        },
        "video-output-format": {
            "hdmi": {"is-color-fmt": 0, "color-fmt": 3, "is-quant-range": 0, "quant-range": 2, "is-sat-range": 0, "sat-range": 2},
            "sdi": {"is-color-fmt": 0, "color-fmt": 3, "is-quant-range": 0, "quant-range": 2, "is-sat-range": 0, "sat-range": 2}
        },
        "video-color": {
            "hdmi": {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0},
            "sdi": {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0}
        },
        "volume": {
            "is-spi": 1,
            "spi-gain": 0,
            "is-linein": 1,
            "linein-gain": 0,
            "is-lineout": 1,
            "lineout-gain": 0,
            "enable-mic-bias": 0
        },
        "audio-mixer": {"enable-spi-mix": 0, "enable-lineout-mix": 1},
        "enable-deinterlace": 0,
        "deinterlace-mode": 1,
        "3d-output": {"enable": 0, "mode": 1},
        "main-stream": {
            "is-auto": 0,
            "codec": 1,
            "cx": 3840,
            "cy": 2160,
            "duration": 333333,
            "kbps": 25600,
            "gop": 60,
            "fourcc": 0,
            "profile": 0,
            "cbrstat": 60,
            "fullrange": 0,
            "is-vbr": 1,
            "min-vbr-qp": 12,
            "max-vbr-qp": 36,
            "is-time-code-sei": 0,
            "is-closed-caption-sei": 0,
            "ar-convert-mode": 2,
            "rotation": 0,
            "mirroring": 0,
            "crop": {
                "is-use": 0,
                "effect": {"x-offset": 0, "y-offset": 0, "act-w": 3840, "act-h": 2160},
                "crop": {"x-offset": 0, "y-offset": 0, "act-w": 0, "act-h": 0}
            }
        },
        "sub-stream": {
            "enable": 1,
            "codec": 1,
            "cx": 1280,
            "cy": 720,
            "duration": 333667,
            "kbps": 2048,
            "gop": 60,
            "fourcc": 0,
            "profile": 0,
            "cbrstat": 60,
            "fullrange": 0,
            "is-vbr": 0,
            "min-vbr-qp": 0,
            "max-vbr-qp": 0,
            "is-time-code-sei": 0,
            "is-closed-caption-sei": 0,
            "ar-convert-mode": 2,
            "rotation": 0,
            "mirroring": 0,
            "crop": {
                "is-use": 0,
                "effect": {"x-offset": 0, "y-offset": 0, "act-w": 1280, "act-h": 720},
                "crop": {"x-offset": 0, "y-offset": 0, "act-w": 0, "act-h": 0}
            }
        },
        "channel-mask": 255,
        "audio-stream-count": 1,
        "audio-streams": [
            {"sample-rate": 48000, "channels": 2, "kbps": 192, "ch0": 0, "ch1": 1, "ch2": 2, "ch3": 3, "ch4": 4, "ch5": 5, "ch6": 6, "ch7": 7, "use-lfe": 0}
        ],
        "eth": {"is-dhcp": 1, "ip": "", "mask": "", "router": "", "dns": ""},
        "enable-station": 1,
        "wifi": [
            {"name": "Sector 2024", "passwd": "c2VjdG9yMjAyNA==", "identity": "", "freq": 0, "level": 0, "secu": 3, "is-auto": 1, "is-use": 0, "is-hide": 0, "is-dhcp": 1, "ip": "", "mask": "", "router": "", "dns": ""},
            {"name": "BLACKHATEUROPE2024", "passwd": "QkhFVVJPUEUyMDI0", "identity": "", "freq": 0, "level": 0, "secu": 3, "is-auto": 1, "is-use": 0, "is-hide": 0, "is-dhcp": 1, "ip": "", "mask": "", "router": "", "dns": ""}
        ],
        "softap": {"is-softap": 0, "is-visible": 1, "softap-ssid": "B313231201201", "softap-passwd": "31201201"},
        "rndis": {"ip": "192.168.66.1", "mask": "255.255.255.0"},
        "stream-server": [
            {"id": 0, "type": 121, "name": "SRT Listener", "is-use": 1, "port": 8000, "max-connections": 1, "latency": 200, "bandwidth": 25, "net-mode": 0, "stream-index": 1, "aes": 0, "aes-word": "", "mtu": 1496, "audio": 0, "audio-streams": 1, "is-media-hub": 0}
        ],
        "rec-channels": [
            {
                "id": 0, "type": 0, "is-use": 1, "stream-index": 0, "mode": 0,
                "dir-name": f"{magewell_id}_REC_Folder",
                "file-prefix": 0,
                "prefix-name": f"{magewell_id}_",
                "file-suffix": 0,
                "time-unit": 10, "audio": 0
            },
            {
                "id": 1, "type": 1, "is-use": 0, "stream-index": 0, "mode": 0,
                "dir-name": magewell_id,
                "file-prefix": 0,
                "prefix-name": magewell_id,
                "file-suffix": 0,
                "time-unit": 90, "audio": 0
            },
            {
                "id": 2, "type": 2, "is-use": 0, "stream-index": 0, "mode": 0,
                "dir-name": "REC_Folder",
                "file-prefix": 0,
                "prefix-name": "VID",
                "file-suffix": 0,
                "time-unit": 30, "audio": 0
            }
         ],
        "nas": [],
        "send-file-cloud": [],
        "schedulers": [],
        "image": [
            {"id": 0, "name": "", "type": 1, "path": "/surface-image/image0.png", "time": 17091101447340797, "cx": 401, "cy": 50}
        ],
        "surface": {"main-surface": 0, "second-surface": 0, "surfaces": []},
        "web": {"is-http": 1, "http-port": 80, "is-https": 0, "https-port": 443, "is-cert-valid": 0, "is-cert-key-valid": 0, "theme": 0},
        "rec": {"is-auto": 0, "trigger-mode": 0},
        "living": {
            "ts": {"mtu": 1496},
            "hls-push": {"seg-count": 3, "seg-duration": 3},
            "ndi-find": {"group-name": "Public", "extra-ips": "", "enable-discovery": 0, "discovery-server": ""}
        },
        "date-time": {"timezone": "America/Los_Angeles", "is-auto": 1, "ntp-server": "0.pool.ntp.org", "ntp-server-backup": "1.pool.ntp.org"},
        "lcd-control": {"no-touch": 0, "page-idx": 1, "no-flip": 0, "duration": 666667}
    }

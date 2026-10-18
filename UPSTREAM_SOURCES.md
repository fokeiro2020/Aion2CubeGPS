# Attribution and integration

The file `working_aion_radar.py` is a copy of `aion2_radar.py` directly provided by the user. Its original `PureStreamEngine`, `RadarState`, and `Pure2DRadarApp` logic are **left intact** for matching their tested behavior. `working_network_capture.py` is a new adapter that forwards its events into the existing Cube Finder GUI without running a second sniffer.

Our legacy v12 decoder (`aion_protocol_v11.py`, `network_capture.py`) remains separately selectable for comparison; it is not used in default working mode.

As the uploaded source's distribution license is not established here, do not republish this bundle publicly without reviewing permission/licensing. Other file origins are as described in prior project versions.

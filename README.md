# grmon-hw-server
GRMON to hw_server proxy

Allows [grmon](https://gaisler.com/index.php/downloads/debug-tools) to share `hw_server` with `vivado`.

Run as
```
HW_URL="TCP:localhost:3121" ./grmon_proxy.py
```
This will print out PTY (like `/dev/pts/0`). Use it to connect `grmon` like in the example design `leon3-ahbfile`:
```
grmon -uart /dev/pts/0
```

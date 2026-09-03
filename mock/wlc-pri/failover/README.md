Intentionally empty.

In the `failover` scenario the LAB-DC1 site is gone, so WLC-PRI is unreachable.
`app/connect.py` (`UNREACHABLE`) returns a connection failure for WLC-PRI in this
scenario without attempting a mock, which is exactly what a real management-plane
outage looks like to the toolkit.

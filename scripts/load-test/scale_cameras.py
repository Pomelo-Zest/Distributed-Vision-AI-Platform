from __future__ import annotations

import json
import sys


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    cameras = []
    for index in range(1, count + 1):
        cameras.append(
            {
                "id": f"cam-virtual-{index:03d}",
                "name": f"Virtual Camera {index:03d}",
                "source_uri": f"mock://virtual-{index:03d}",
                "target_fps": 3 + (index % 4),
                "metadata": {
                    "zone": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                    "line": [[0.1, 0.5], [0.9, 0.5]],
                    "loitering_zone": [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]],
                },
            }
        )
    print(json.dumps(cameras, indent=2))


if __name__ == "__main__":
    main()


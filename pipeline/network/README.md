# Network Pipeline

Tools for building canonical network.xml from various sources.

## From OpenStreetMap

```bash
# Using predefined city
python -m pipeline.network.build_network_from_osm \
    --city sioux_falls \
    --output scenarios/sioux_falls_tier50k/network.xml

# Using custom bounding box (north,south,east,west)
python -m pipeline.network.build_network_from_osm \
    --bbox "43.59,-43.50,-96.68,-96.78" \
    --output scenarios/custom/network.xml
```

### Predefined Cities

| Key                 | Description                         | Radius |
| ------------------- | ----------------------------------- | ------ |
| `sioux_falls`       | Sioux Falls, SD (classic benchmark) | 5 km   |
| `anaheim`           | Anaheim, CA (classic benchmark)     | 4 km   |
| `austin_downtown`   | Austin Downtown, TX                 | 3 km   |
| `manhattan_midtown` | Manhattan Midtown, NY               | 2 km   |
| `sf_downtown`       | San Francisco Downtown, CA          | 2.5 km |

### Dependencies

```bash
pip install osmnx
```

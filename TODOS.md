- We can use something like this inside <settings.py>

```
BANJO_UTILS_CONFIG = {
    "WAIT_FOR_RESOURCES": {
        "ALIAS": {
            "dev": ["db", "redis", "minio"],
            "alpha": ["db", "redis", "minio"],
            "stage": ["db", "redis"],
        }
    }
}
```

```
- Check if we can define enum for db, redis, minio
- If not we need to add post checks
OR
- ./manage.py wait-for-resources --db --redis --minio
- maybe use health_check integrations
```

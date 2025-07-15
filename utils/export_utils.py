import base64
import datetime
import logging

logger = logging.getLogger("climbing_app")


async def export_redis_database(redis_store) -> str:
    """Export Redis database using standard Redis commands (excludes sessions and temp data, includes binary images)"""
    
    try:
        # Get keys from both text and binary Redis databases
        text_keys = redis_store.redis.keys("*")
        binary_keys = redis_store.binary_redis.keys("*")
        
        # Start building the Redis commands file
        commands = []
        export_count = 0
        
        # Add header comment
        commands.append("# Redis Database Export")
        commands.append(f"# Generated: {datetime.datetime.now().isoformat()}")
        commands.append("# Excludes: sessions and temp data")
        commands.append("# Includes: text data (DB 0) and binary images (DB 1)")
        commands.append("# Usage: grep -v '^#' this_file.redis | redis-cli")
        commands.append("# Note: Uses standard Redis commands for maximum compatibility")
        commands.append("")
        
        # Helper function to escape Redis values
        def escape_redis_value(value):
            if isinstance(value, str):
                # Escape quotes and backslashes
                return value.replace('\\', '\\\\').replace('"', '\\"')
            return str(value)
        
        # Process text database keys (DB 0)
        commands.append("# === TEXT DATA (DB 0) ===")
        commands.append("SELECT 0")
        for key in text_keys:
            # Skip sensitive data
            if (key.startswith("session:") or 
                key.startswith("temp:")):
                continue
            
            try:
                # Get key type and TTL
                key_type = redis_store.redis.type(key)
                ttl = redis_store.redis.ttl(key)
                
                if key_type == "string":
                    value = redis_store.redis.get(key)
                    if value is not None:
                        escaped_value = escape_redis_value(value)
                        commands.append(f'SET "{key}" "{escaped_value}"')
                        if ttl > 0:
                            commands.append(f'EXPIRE "{key}" {ttl}')
                        export_count += 1
                        
                elif key_type == "hash":
                    hash_data = redis_store.redis.hgetall(key)
                    if hash_data:
                        hash_args = []
                        for field, value in hash_data.items():
                            hash_args.extend([f'"{escape_redis_value(field)}"', f'"{escape_redis_value(value)}"'])
                        commands.append(f'HSET "{key}" {" ".join(hash_args)}')
                        if ttl > 0:
                            commands.append(f'EXPIRE "{key}" {ttl}')
                        export_count += 1
                        
                elif key_type == "set":
                    set_members = redis_store.redis.smembers(key)
                    if set_members:
                        escaped_members = [f'"{escape_redis_value(member)}"' for member in set_members]
                        commands.append(f'SADD "{key}" {" ".join(escaped_members)}')
                        if ttl > 0:
                            commands.append(f'EXPIRE "{key}" {ttl}')
                        export_count += 1
                        
                elif key_type == "list":
                    list_values = redis_store.redis.lrange(key, 0, -1)
                    if list_values:
                        escaped_values = [f'"{escape_redis_value(value)}"' for value in list_values]
                        commands.append(f'RPUSH "{key}" {" ".join(escaped_values)}')
                        if ttl > 0:
                            commands.append(f'EXPIRE "{key}" {ttl}')
                        export_count += 1
                        
                elif key_type == "zset":
                    zset_data = redis_store.redis.zrange(key, 0, -1, withscores=True)
                    if zset_data:
                        zset_args = []
                        for member, score in zset_data:
                            zset_args.extend([str(score), f'"{escape_redis_value(member)}"'])
                        commands.append(f'ZADD "{key}" {" ".join(zset_args)}')
                        if ttl > 0:
                            commands.append(f'EXPIRE "{key}" {ttl}')
                        export_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to export text key {key}: {e}")
                continue
        
        # Process binary database keys (DB 1) 
        commands.append("")
        commands.append("# === BINARY DATA (DB 1) ===")
        commands.append("SELECT 1")
        for key in binary_keys:
            # Convert bytes key to string for processing
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            
            # Skip temp images
            if key_str.startswith("image:temp:"):
                continue
                
            try:
                # Get binary data and TTL
                binary_data = redis_store.binary_redis.get(key)
                ttl = redis_store.binary_redis.ttl(key)
                
                if binary_data is not None:
                    # Encode binary data as base64 for storage
                    encoded_data = base64.b64encode(binary_data).decode('ascii')
                    # Store as string with base64 marker
                    commands.append(f'SET "{key_str}" "base64:{encoded_data}"')
                    if ttl > 0:
                        commands.append(f'EXPIRE "{key_str}" {ttl}')
                    export_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to export binary key {key_str}: {e}")
                continue
        
        # Add footer with statistics
        total_keys = len(text_keys) + len(binary_keys)
        commands.append("")
        commands.append(f"# Export completed: {export_count} keys exported")
        commands.append(f"# Total keys found: {total_keys} (Text DB: {len(text_keys)}, Binary DB: {len(binary_keys)})")
        commands.append(f"# Excluded keys: {total_keys - export_count}")
        commands.append("")
        commands.append("# NOTE: Binary data is stored as base64-encoded strings with 'base64:' prefix")
        commands.append("# You may need to decode them back to binary format depending on your application")
        
        # Join all commands
        redis_export = "\n".join(commands)
        
        logger.info(f"Redis export completed: {export_count} keys exported out of {total_keys} total keys (Text: {len(text_keys)}, Binary: {len(binary_keys)})")
        return redis_export
        
    except Exception as e:
        logger.error(f"Error during Redis export: {e}")
        raise 

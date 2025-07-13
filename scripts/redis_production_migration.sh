#!/bin/bash

# Redis Production Migration Script
# Provides idiomatic methods for transferring Redis data to production

set -e

# Configuration
SOURCE_HOST="${SOURCE_HOST:-localhost}"
SOURCE_PORT="${SOURCE_PORT:-6379}"
SOURCE_PASSWORD="${SOURCE_PASSWORD:-}"
TARGET_HOST="${TARGET_HOST:-}"
TARGET_PORT="${TARGET_PORT:-6379}"
TARGET_PASSWORD="${TARGET_PASSWORD:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}🚀 Redis Production Migration Tool${NC}"
    echo -e "${BLUE}===================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Method 1: RDB Snapshot (Recommended for most cases)
method_rdb_snapshot() {
    local output_file="${1:-redis_backup_$(date +%Y%m%d_%H%M%S).rdb}"
    
    print_info "Creating RDB snapshot: $output_file"
    
    # Build redis-cli command for source
    local cmd="redis-cli -h $SOURCE_HOST -p $SOURCE_PORT"
    if [ -n "$SOURCE_PASSWORD" ]; then
        cmd="$cmd -a $SOURCE_PASSWORD"
    fi
    
    # Create RDB dump
    $cmd --rdb "$output_file"
    
    if [ $? -eq 0 ]; then
        print_success "RDB snapshot created: $output_file"
        echo "📁 File size: $(ls -lh "$output_file" | awk '{print $5}')"
        
        if [ -n "$TARGET_HOST" ]; then
            print_info "To restore to production, run:"
            echo "  redis-cli -h $TARGET_HOST -p $TARGET_PORT --rdb-file $output_file"
        fi
    else
        print_error "Failed to create RDB snapshot"
        exit 1
    fi
}

# Method 2: Redis Migration using MIGRATE command
method_migrate_keys() {
    if [ -z "$TARGET_HOST" ]; then
        print_error "Target host required for migration"
        exit 1
    fi
    
    print_info "Migrating keys from $SOURCE_HOST:$SOURCE_PORT to $TARGET_HOST:$TARGET_PORT"
    
    # Build redis-cli command for source
    local source_cmd="redis-cli -h $SOURCE_HOST -p $SOURCE_PORT"
    if [ -n "$SOURCE_PASSWORD" ]; then
        source_cmd="$source_cmd -a $SOURCE_PASSWORD"
    fi
    
    # Get all keys and migrate them
    local keys=$($source_cmd --scan)
    local total_keys=$(echo "$keys" | wc -l)
    local current=0
    
    print_info "Found $total_keys keys to migrate"
    
    for key in $keys; do
        current=$((current + 1))
        echo -ne "\r📦 Migrating key $current/$total_keys: $key"
        
        # Migrate key to target
        $source_cmd MIGRATE "$TARGET_HOST" "$TARGET_PORT" "$key" 0 5000 ${TARGET_PASSWORD:+AUTH $TARGET_PASSWORD}
    done
    
    echo ""
    print_success "Migration completed: $total_keys keys migrated"
}

# Method 3: JSON Export/Import (Most portable)
method_json_export() {
    local output_file="${1:-redis_export_$(date +%Y%m%d_%H%M%S).json}"
    
    print_info "Creating JSON export: $output_file"
    
    # Build redis-cli command
    local cmd="redis-cli -h $SOURCE_HOST -p $SOURCE_PORT"
    if [ -n "$SOURCE_PASSWORD" ]; then
        cmd="$cmd -a $SOURCE_PASSWORD"
    fi
    
    # Create JSON export
    cat << 'EOF' > /tmp/redis_export.lua
local keys = redis.call('keys', '*')
local result = {}
for i=1,#keys do
    local key = keys[i]
    local keytype = redis.call('type', key)['ok']
    local ttl = redis.call('ttl', key)
    
    local value
    if keytype == 'string' then
        value = redis.call('get', key)
    elseif keytype == 'hash' then
        value = redis.call('hgetall', key)
    elseif keytype == 'set' then
        value = redis.call('smembers', key)
    elseif keytype == 'list' then
        value = redis.call('lrange', key, 0, -1)
    elseif keytype == 'zset' then
        value = redis.call('zrange', key, 0, -1, 'withscores')
    end
    
    result[key] = {
        type = keytype,
        value = value,
        ttl = ttl > 0 and ttl or nil
    }
end
return cjson.encode(result)
EOF
    
    $cmd --eval /tmp/redis_export.lua > "$output_file"
    rm /tmp/redis_export.lua
    
    if [ $? -eq 0 ]; then
        print_success "JSON export created: $output_file"
        echo "📁 File size: $(ls -lh "$output_file" | awk '{print $5}')"
    else
        print_error "Failed to create JSON export"
        exit 1
    fi
}

# Method 4: Redis Sync (Real-time replication)
method_redis_sync() {
    if [ -z "$TARGET_HOST" ]; then
        print_error "Target host required for sync"
        exit 1
    fi
    
    print_info "Setting up Redis sync from $SOURCE_HOST:$SOURCE_PORT to $TARGET_HOST:$TARGET_PORT"
    
    # Build redis-cli command for target
    local target_cmd="redis-cli -h $TARGET_HOST -p $TARGET_PORT"
    if [ -n "$TARGET_PASSWORD" ]; then
        target_cmd="$target_cmd -a $TARGET_PASSWORD"
    fi
    
    # Set target as replica of source
    if [ -n "$SOURCE_PASSWORD" ]; then
        $target_cmd CONFIG SET masterauth "$SOURCE_PASSWORD"
    fi
    
    $target_cmd SLAVEOF "$SOURCE_HOST" "$SOURCE_PORT"
    
    print_info "Waiting for initial sync to complete..."
    
    # Wait for sync
    while true; do
        local sync_status=$($target_cmd INFO replication | grep "master_sync_in_progress:0")
        if [ -n "$sync_status" ]; then
            break
        fi
        sleep 1
        echo -n "."
    done
    
    echo ""
    print_success "Sync completed successfully"
    print_warning "Target is now a replica. Run 'SLAVEOF NO ONE' on target to make it independent"
    
    echo ""
    print_info "To make target independent, run:"
    echo "  $target_cmd SLAVEOF NO ONE"
}

# Method 5: Docker Volume Copy (For Docker setups)
method_docker_volume() {
    local source_container="${1:-climbing_redis}"
    local backup_file="${2:-redis_backup_$(date +%Y%m%d_%H%M%S).tar.gz}"
    
    print_info "Creating Docker volume backup: $backup_file"
    
    # Create backup of Redis volume
    docker run --rm -v climbing_redis_data:/data -v "$(pwd):/backup" alpine tar czf "/backup/$backup_file" -C /data .
    
    if [ $? -eq 0 ]; then
        print_success "Docker volume backup created: $backup_file"
        echo "📁 File size: $(ls -lh "$backup_file" | awk '{print $5}')"
        
        print_info "To restore in production:"
        echo "  1. Create volume: docker volume create production_redis_data"
        echo "  2. Restore: docker run --rm -v production_redis_data:/data -v \$(pwd):/backup alpine tar xzf /backup/$backup_file -C /data"
    else
        print_error "Failed to create Docker volume backup"
        exit 1
    fi
}

# Show data info
show_data_info() {
    local cmd="redis-cli -h $SOURCE_HOST -p $SOURCE_PORT"
    if [ -n "$SOURCE_PASSWORD" ]; then
        cmd="$cmd -a $SOURCE_PASSWORD"
    fi
    
    print_info "Current Redis data information:"
    echo "📊 Database info:"
    $cmd INFO keyspace | grep -E "^db[0-9]:"
    echo ""
    echo "💾 Memory usage:"
    $cmd INFO memory | grep "used_memory_human:"
    echo ""
    echo "🔧 Redis version:"
    $cmd INFO server | grep "redis_version:"
}

# Main menu
show_menu() {
    print_header
    echo ""
    echo "Choose migration method:"
    echo "1) RDB Snapshot (Recommended - Fast, complete backup)"
    echo "2) Key Migration (Live migration with MIGRATE command)"
    echo "3) JSON Export (Most portable, human-readable)"
    echo "4) Redis Sync (Real-time replication)"
    echo "5) Docker Volume Copy (For Docker deployments)"
    echo "6) Show Data Info"
    echo "q) Quit"
    echo ""
}

# Main script
main() {
    if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        print_header
        echo ""
        echo "Usage: $0 [method] [options]"
        echo ""
        echo "Methods:"
        echo "  rdb      - Create RDB snapshot"
        echo "  migrate  - Migrate keys to target"
        echo "  json     - Create JSON export"
        echo "  sync     - Set up Redis replication"
        echo "  docker   - Create Docker volume backup"
        echo "  info     - Show data information"
        echo ""
        echo "Environment variables:"
        echo "  SOURCE_HOST, SOURCE_PORT, SOURCE_PASSWORD"
        echo "  TARGET_HOST, TARGET_PORT, TARGET_PASSWORD"
        echo ""
        echo "Examples:"
        echo "  $0 rdb                                    # Create RDB snapshot"
        echo "  TARGET_HOST=prod.redis.com $0 migrate    # Migrate to production"
        echo "  $0 json my_export.json                   # Create JSON export"
        exit 0
    fi
    
    # Direct method execution
    case "$1" in
        "rdb")
            method_rdb_snapshot "$2"
            ;;
        "migrate")
            method_migrate_keys
            ;;
        "json")
            method_json_export "$2"
            ;;
        "sync")
            method_redis_sync
            ;;
        "docker")
            method_docker_volume "$2" "$3"
            ;;
        "info")
            show_data_info
            ;;
        "")
            # Interactive mode
            while true; do
                show_menu
                read -p "Enter choice [1-6, q]: " choice
                case $choice in
                    1)
                        read -p "Output file (optional): " output_file
                        method_rdb_snapshot "$output_file"
                        ;;
                    2)
                        method_migrate_keys
                        ;;
                    3)
                        read -p "Output file (optional): " output_file
                        method_json_export "$output_file"
                        ;;
                    4)
                        method_redis_sync
                        ;;
                    5)
                        read -p "Container name (optional): " container
                        read -p "Backup file (optional): " backup
                        method_docker_volume "$container" "$backup"
                        ;;
                    6)
                        show_data_info
                        ;;
                    q|Q)
                        echo "Goodbye!"
                        exit 0
                        ;;
                    *)
                        print_error "Invalid choice"
                        ;;
                esac
                echo ""
                read -p "Press Enter to continue..."
            done
            ;;
        *)
            print_error "Unknown method: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
}

main "$@" 

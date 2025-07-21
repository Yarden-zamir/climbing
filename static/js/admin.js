/**
 * Admin Panel JavaScript
 * Handles user management, resource assignment, and system administration
 */

class AdminPanel {
    constructor() {
        this.currentUser = null;
        this.users = [];
        this.resources = [];
        this.currentSection = 'dashboard';
        this.selectedResource = null;
        this.selectedUser = null;
        
        this.init();
    }

    async init() {
        // Check if user is admin
        await this.checkAdminAccess();
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Load initial data
        await this.loadDashboardStats();
        await this.loadUsers();
        await this.loadAllResources();
    }

    async checkAdminAccess() {
        try {
            const response = await fetch('/api/auth/user');
            const data = await response.json();
            
            if (!data.authenticated) {
                window.location.href = '/auth/login';
                return;
            }
            
            this.currentUser = data.user;
            
            // Check if user has admin permissions by trying to access admin stats
            const adminResponse = await fetch('/api/admin/stats');
            if (!adminResponse.ok) {
                if (adminResponse.status === 403) {
                    this.showError('Access denied. Admin privileges required.');
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 3000);
                } else {
                    this.showError('Failed to verify admin access.');
                }
                return;
            }
            
        } catch (error) {
            console.error('Error checking admin access:', error);
            this.showError('Error checking admin access.');
        }
    }

    setupEventListeners() {
        // Navigation buttons
        document.querySelectorAll('.admin-nav-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.switchSection(e.target.dataset.section);
            });
        });

        // Modal close buttons
        document.querySelectorAll('.close').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                this.closeModal(modal.id);
            });
        });

        // Click outside modal to close
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeModal(modal.id);
                }
            });
        });

        // Role form submission
        document.getElementById('roleForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.updateUserRole();
        });

        // Add owner form submission
        document.getElementById('addOwnerForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.addOwner();
        });

        // Migration button
        document.getElementById('migrate-btn').addEventListener('click', () => {
            this.migrateResources();
        });

        // Refresh metadata button
        document.getElementById('refresh-metadata-btn').addEventListener('click', () => {
            this.refreshMetadata();
        });

        // Export database button
        document.getElementById('export-database-btn').addEventListener('click', () => {
            this.exportDatabase();
        });

        // Achievements management
        document.getElementById('add-achievement-btn').addEventListener('click', () => {
            this.addAchievement();
        });

        // Skills management
        document.getElementById('add-skill-btn').addEventListener('click', () => {
            this.addSkill();
        });
    }

    switchSection(section) {
        // Update navigation
        document.querySelectorAll('.admin-nav-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-section="${section}"]`).classList.add('active');

        // Update sections
        document.querySelectorAll('.admin-section').forEach(sec => {
            sec.classList.remove('active');
        });
        document.getElementById(section).classList.add('active');

        this.currentSection = section;

        // Load section-specific data
        if (section === 'users' && this.users.length === 0) {
            this.loadUsers();
        } else if (section === 'resources' && this.resources.length === 0) {
            this.loadAllResources();
        } else if (section === 'achievements') {
            this.loadAchievements();
        } else if (section === 'skills') {
            this.loadSkills();
        } else if (section === 'notifications') {
            this.setupNotificationsTab();
        }
    }

    async loadDashboardStats() {
        try {
            const response = await fetch('/api/admin/stats');
            if (!response.ok) throw new Error('Failed to load stats');
            
            const stats = await response.json();
            
            document.getElementById('total-users').textContent = stats.users.total;
            document.getElementById('admin-users').textContent = stats.users.admins;
            document.getElementById('total-albums').textContent = stats.resources.albums.total;
            document.getElementById('total-crew').textContent = stats.resources.crew_members.total;
            document.getElementById('unowned-resources').textContent = 
                stats.resources.albums.unowned + stats.resources.crew_members.unowned;
        } catch (error) {
            console.error('Error loading dashboard stats:', error);
            this.showError('Failed to load dashboard statistics.');
        }
    }

    async loadUsers() {
        try {
            const response = await fetch('/api/admin/users');
            if (!response.ok) throw new Error('Failed to load users');
            
            this.users = await response.json();
            this.renderUsersTable();
        } catch (error) {
            console.error('Error loading users:', error);
            this.showError('Failed to load users.');
        }
    }

    renderUsersTable() {
        const tbody = document.getElementById('users-tbody');
        
        if (this.users.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="empty-state">
                        <div class="icon">👥</div>
                        <p>No users found</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.users.map(user => `
            <tr>
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        ${this.generateUserAvatar(user)}
                        <div>
                            <div style="font-weight: 500;">${user.name}</div>
                            <div style="font-size: 0.8rem; color: #7f8c8d;">${user.email}</div>
                        </div>
                    </div>
                </td>
                <td style="display: none;">${user.email}</td>
                <td>
                    <span class="role-badge role-${user.role}">
                        ${user.role.toUpperCase()}
                    </span>
                </td>
                <td>${user.owned_albums}</td>
                <td>${user.owned_crew_members}</td>
                <td>${this.formatDate(user.created_at)}</td>
                <td>
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                        <button class="action-btn btn-primary" 
                                onclick="adminPanel.openRoleModal('${user.id}', '${user.role}')">
                            Change Role
                        </button>
                        <button class="action-btn btn-secondary" 
                                onclick="adminPanel.openUserNotificationSettings('${user.id}', '${user.name}')">
                            🔔 Notifications
                        </button>
                    </div>
                </td>
            </tr>
        `).join('');
    }

    // Helper method to get profile picture URL
    getProfilePictureUrl(user) {
        if (!user || !user.id) return '/static/favicon/favicon-32x32.png';
        
        // If picture starts with /redis-image/ or /api/profile-picture/, use it as is
        if (user.picture && (
            user.picture.startsWith('/redis-image/') || 
            user.picture.startsWith('/api/profile-picture/')
        )) {
            return user.picture;
        }
        
        // Otherwise use our cached endpoint
        return `/api/profile-picture/${user.id}`;
    }

    generateUserAvatar(user) {
        const initials = this.getUserInitials(user.name);
        const avatarId = `avatar-${user.id}`;
        
        return `
            <div class="user-avatar-container" style="position: relative;">
                <img id="${avatarId}" 
                     src="${this.getProfilePictureUrl(user)}" 
                     alt="${user.name}"
                     style="width: 40px; height: 40px; border-radius: 50%; object-fit: cover; border: 2px solid rgba(255, 255, 255, 0.1);"
                     onload="this.style.display='block'; this.nextElementSibling.style.display='none';"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                <div class="user-avatar-fallback" 
                     style="width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                            display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; 
                            font-size: 0.9rem; border: 2px solid rgba(255, 255, 255, 0.1);">
                    ${initials}
                </div>
            </div>
        `;
    }

    getUserInitials(name) {
        if (!name) return '??';
        return name
            .split(' ')
            .map(word => word.charAt(0).toUpperCase())
            .slice(0, 2)
            .join('');
    }

    getResourceTypeClass(type) {
        switch (type) {
            case 'album':
                return 'role-user';
            case 'crew_member':
                return 'role-admin';
            case 'meme':
                return 'role-pending';
            default:
                return 'role-user';
        }
    }

    getResourceTypeLabel(type) {
        switch (type) {
            case 'album':
                return 'ALBUM';
            case 'crew_member':
                return 'CREW';
            case 'meme':
                return 'MEME';
            default:
                return type.toUpperCase();
        }
    }

    async loadAllResources() {
        try {
            const response = await fetch('/api/admin/resources/all');
            if (!response.ok) throw new Error('Failed to load resources');
            
            const data = await response.json();
            this.resources = data.resources;
            this.renderResourcesTable();
        } catch (error) {
            console.error('Error loading resources:', error);
            this.showError('Failed to load resources.');
        }
    }

    renderResourcesTable() {
        const tbody = document.getElementById('resources-tbody');
        
        if (this.resources.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="empty-state">
                        <div class="icon">📁</div>
                        <p>No resources found</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.resources.map(resource => `
            <tr>
                <td>
                    <span class="role-badge ${this.getResourceTypeClass(resource.type)}">
                        ${this.getResourceTypeLabel(resource.type)}
                    </span>
                </td>
                <td>${resource.title || resource.name}</td>
                <td style="font-family: monospace; font-size: 0.8rem;">
                    ${this.truncateText(resource.id, 40)}
                </td>
                <td>
                    ${resource.owners && resource.owners.length > 0 ? this.generateOwnersDisplay(resource.owners, resource.type, resource.id) : 
                      '<span style="color: #f39c12; font-weight: 500;">⚠️ Unowned</span>'}
                </td>
                <td>${this.formatDate(resource.created_at)}</td>
                <td>
                    <button class="action-btn btn-success" 
                            onclick="adminPanel.openAddOwnerModal('${resource.type}', '${resource.id}')">
                        Add Owner
                    </button>
                </td>
            </tr>
        `).join('');
    }

    generateOwnersDisplay(owners, resourceType, resourceId) {
        if (!owners || owners.length === 0) return '<span style="color: #f39c12;">Unowned</span>';
        
        // Show all owners as pills
        const ownerPills = owners.map(owner => this.generateOwnerPill(owner, resourceType, resourceId)).join('');
        
        return `
            <div class="owners-container">
                ${ownerPills}
            </div>
        `;
    }

    generateOwnerPill(owner, resourceType, resourceId) {
        const initials = this.getUserInitials(owner.name);
        const avatarId = `pill-avatar-${owner.id}-${Math.random().toString(36).substr(2, 9)}`;
        
        return `
            <div class="owner-pill" title="${owner.name} (${owner.email})">
                <div class="user-avatar-container" style="position: relative;">
                    <img id="${avatarId}" 
                         src="${this.getProfilePictureUrl(owner)}" 
                         alt="${owner.name}"
                         style="width: 16px; height: 16px; border-radius: 50%; object-fit: cover;"
                         onload="this.style.display='block'; this.nextElementSibling.style.display='none';"
                         onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="user-avatar-fallback" 
                         style="width: 16px; height: 16px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; 
                                font-size: 8px;">
                        ${initials}
                    </div>
                </div>
                <span style="color: #495057; font-weight: 500;">${this.truncateText(owner.name, 12)}</span>
                <button onclick="adminPanel.removeOwner('${resourceType}', '${resourceId}', '${owner.id}', event)" 
                        style="background: none; border: none; color: #dc3545; font-size: 12px; padding: 0; margin-left: 2px; 
                               cursor: pointer; display: flex; align-items: center; justify-content: center; width: 14px; height: 14px;
                               border-radius: 50%; transition: background-color 0.2s;"
                        onmouseover="this.style.backgroundColor='#dc3545'; this.style.color='white';"
                        onmouseout="this.style.backgroundColor='transparent'; this.style.color='#dc3545';"
                        title="Remove ${owner.name} as owner">×</button>
            </div>
        `;
    }

    generateSingleOwnerDisplay(owner) {
        const initials = this.getUserInitials(owner.name);
        const avatarId = `owner-avatar-${owner.id}`;
        
        return `
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                ${this.generateOwnerAvatar(owner, 24)}
                <div style="font-size: 0.9rem;">
                    <div style="font-weight: 500; color: #2c3e50;">${owner.name}</div>
                    <div style="font-size: 0.8rem; color: #7f8c8d;">${owner.email}</div>
                </div>
            </div>
        `;
    }

    generateOwnerAvatar(owner, size) {
        const initials = this.getUserInitials(owner.name);
        const avatarId = `owner-avatar-${owner.id}`;
        
        return `
            <div class="user-avatar-container" style="position: relative;">
                <img id="${avatarId}" 
                     src="${this.getProfilePictureUrl(owner)}" 
                     alt="${owner.name}"
                     style="width: ${size}px; height: ${size}px; border-radius: 50%; object-fit: cover; border: 1px solid rgba(255, 255, 255, 0.1);"
                     onload="this.style.display='block'; this.nextElementSibling.style.display='none';"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                <div class="user-avatar-fallback" 
                     style="width: ${size}px; height: ${size}px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                            display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; 
                            font-size: ${size * 0.4}px; border: 1px solid rgba(255, 255, 255, 0.1);">
                    ${initials}
                </div>
            </div>
        `;
    }

    openRoleModal(userId, currentRole) {
        this.selectedUser = userId;
        document.getElementById('userRole').value = currentRole;
        this.showModal('roleModal');
    }

    async openAddOwnerModal(resourceType, resourceId) {
        this.selectedResource = { type: resourceType, id: resourceId };
        
        // Find the current resource to get existing owners
        const currentResource = this.resources.find(r => r.type === resourceType && r.id === resourceId);
        const existingOwners = currentResource ? (currentResource.owners || []) : [];
        const existingOwnerIds = existingOwners.map(owner => owner.id);
        
        // Populate user dropdown, excluding existing owners
        const userSelect = document.getElementById('targetUser');
        const availableUsers = this.users.filter(user => !existingOwnerIds.includes(user.id));
        
        if (availableUsers.length === 0) {
            userSelect.innerHTML = '<option value="">All users are already owners</option>';
            userSelect.disabled = true;
        } else {
            userSelect.innerHTML = availableUsers.map(user => 
                `<option value="${user.id}">${user.name} (${user.email})</option>`
            ).join('');
            userSelect.disabled = false;
        }
        
        // Update modal title to show current owners
        const modalTitle = document.querySelector('#addOwnerModal .modal-header h3');
        if (existingOwners.length > 0) {
            modalTitle.innerHTML = `
                Add Owner to Resource
                <div style="font-size: 0.8rem; font-weight: normal; color: #7f8c8d; margin-top: 0.25rem;">
                    Current owners: ${existingOwners.map(o => o.name).join(', ')}
                </div>
            `;
        } else {
            modalTitle.textContent = 'Add Owner to Resource';
        }
        
        this.showModal('addOwnerModal');
    }

    async updateUserRole() {
        if (!this.selectedUser) return;
        
        const formData = new FormData(document.getElementById('roleForm'));
        const newRole = formData.get('role');
        
        try {
            const response = await fetch(`/api/admin/users/${this.selectedUser}/role?new_role=${encodeURIComponent(newRole)}`, {
                method: 'POST'
            });
            
            if (!response.ok) throw new Error('Failed to update role');
            
            const result = await response.json();
            this.showSuccess(result.message);
            this.closeModal('roleModal');
            
            // Reload users and stats
            await this.loadUsers();
            await this.loadDashboardStats();
            
        } catch (error) {
            console.error('Error updating user role:', error);
            this.showError('Failed to update user role.');
        }
    }

    async addOwner() {
        if (!this.selectedResource) return;
        
        const formData = new FormData(document.getElementById('addOwnerForm'));
        const targetUserId = formData.get('targetUser');
        
        try {
            const response = await fetch('/api/admin/resources/assign', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `resource_type=${this.selectedResource.type}&resource_id=${encodeURIComponent(this.selectedResource.id)}&target_user_id=${targetUserId}`
            });
            
            if (!response.ok) throw new Error('Failed to add owner');
            
            const result = await response.json();
            this.showSuccess(result.message);
            this.closeModal('addOwnerModal');
            
            // Reload resources and stats
            await this.loadAllResources();
            await this.loadDashboardStats();
            
        } catch (error) {
            console.error('Error adding owner:', error);
            this.showError('Failed to add owner.');
        }
    }

    async migrateResources() {
        const btn = document.getElementById('migrate-btn');
        const resultDiv = document.getElementById('migration-result');
        
        btn.disabled = true;
        btn.innerHTML = '<div class="loading"></div> Migrating...';
        
        try {
            const response = await fetch('/api/admin/migrate-resources', {
                method: 'POST'
            });
            
            if (!response.ok) throw new Error('Migration failed');
            
            const result = await response.json();
            
            resultDiv.innerHTML = `
                <div class="alert alert-success">
                    <strong>Migration Complete!</strong><br>
                    Albums migrated: ${result.migrated.albums}<br>
                    Crew members migrated: ${result.migrated.crew_members}
                </div>
            `;
            
            // Reload all data
            await this.loadDashboardStats();
            await this.loadAllResources();
            
        } catch (error) {
            console.error('Error migrating resources:', error);
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <strong>Migration Failed!</strong><br>
                    ${error.message}
                </div>
            `;
        } finally {
            btn.disabled = false;
            btn.innerHTML = 'Migrate Existing Resources';
        }
    }

    async refreshMetadata() {
        try {
            const btn = document.getElementById('refresh-metadata-btn');
            const result = document.getElementById('refresh-metadata-result');
            
            // Clear previous result
            result.className = 'action-result loading';
            result.textContent = 'Refreshing album metadata from Google Photos...';
            
            btn.disabled = true;
            btn.innerHTML = '⏳ Refreshing...';
            
            const response = await fetch('/api/admin/refresh-metadata', {
                method: 'POST'
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            result.className = 'action-result success';
            result.innerHTML = `
                ✅ ${data.message}<br>
                <small>Albums updated: ${data.updated}, Errors: ${data.errors}</small>
            `;
            
        } catch (error) {
            console.error('Metadata refresh error:', error);
            const result = document.getElementById('refresh-metadata-result');
            result.className = 'action-result error';
            result.textContent = `❌ Failed to refresh metadata: ${error.message}`;
        } finally {
            const btn = document.getElementById('refresh-metadata-btn');
            btn.disabled = false;
            btn.innerHTML = '🔄 Refresh Album Metadata';
        }
    }

    async exportDatabase() {
        try {
            const btn = document.getElementById('export-database-btn');
            const result = document.getElementById('export-database-result');
            
            // Clear previous result
            result.className = 'action-result loading';
            result.textContent = 'Exporting database...';
            
            btn.disabled = true;
            btn.innerHTML = '⏳ Exporting...';
            
            const response = await fetch('/api/admin/export', {
                method: 'GET'
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            
            // Get the filename from response headers or generate one
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'climbing_db_export.json';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="?([^"]+)"?/);
                if (match) filename = match[1];
            }
            
            // Create blob and download
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            result.className = 'action-result success';
            result.innerHTML = `
                ✅ Database exported successfully!<br>
                <small>File: ${filename}</small><br><br>
                <strong>To load into Redis:</strong><br>
                <code style="background: #f8f9fa; padding: 4px 8px; border-radius: 4px; font-family: monospace; display: block; margin: 8px 0;">grep -v '^#' ${filename} | redis-cli</code>
                <small>Or for remote Redis: <code>grep -v '^#' ${filename} | redis-cli -h hostname -p 6379</code></small><br>
                <small style="color: #6c757d;">Note: The grep command filters out comment lines before importing</small>
            `;
            
        } catch (error) {
            console.error('Database export error:', error);
            const result = document.getElementById('export-database-result');
            result.className = 'action-result error';
            result.textContent = `❌ Failed to export database: ${error.message}`;
        } finally {
            const btn = document.getElementById('export-database-btn');
            btn.disabled = false;
            btn.innerHTML = '📦 Export Database';
        }
    }

    async loadAchievements() {
        try {
            const response = await fetch('/api/achievements');
            if (!response.ok) throw new Error('Failed to load achievements');
            
            const achievements = await response.json();
            this.renderAchievements(achievements);
        } catch (error) {
            console.error('Error loading achievements:', error);
            this.showError('Failed to load achievements.');
        }
    }

    renderAchievements(achievements) {
        const container = document.getElementById('achievements-list');
        
        if (achievements.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 2rem; color: #7f8c8d;">
                    <div class="icon">🏆</div>
                    <p>No achievements found</p>
                </div>
            `;
            return;
        }

        container.innerHTML = achievements.map(achievement => `
            <div class="achievement-item" style="
                background: white;
                padding: 1rem;
                border-radius: 8px;
                border: 1px solid #ddd;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            ">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span style="font-size: 1.2rem;">🏆</span>
                    <span style="font-weight: 500;">${achievement}</span>
                </div>
                <button class="action-btn btn-danger" onclick="adminPanel.deleteAchievement('${achievement}')">
                    Delete
                </button>
            </div>
        `).join('');
    }

    async addAchievement() {
        const input = document.getElementById('new-achievement-input');
        const resultDiv = document.getElementById('add-achievement-result');
        const achievementName = input.value.trim();

        if (!achievementName) {
            this.showError('Please enter an achievement name.');
            return;
        }

        try {
            // For now, we'll just add it directly to the Redis achievements index
            const response = await fetch('/api/achievements', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ name: achievementName })
            });

            if (!response.ok) throw new Error('Failed to add achievement');

            resultDiv.innerHTML = `
                <div class="alert alert-success">
                    <strong>Success!</strong> Achievement "${achievementName}" has been added.
                </div>
            `;

            input.value = '';
            this.loadAchievements(); // Reload the achievements list
            
        } catch (error) {
            console.error('Error adding achievement:', error);
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <strong>Error!</strong> Failed to add achievement.
                </div>
            `;
        }
    }

    async deleteAchievement(achievementName) {
        if (!confirm(`Are you sure you want to delete the achievement "${achievementName}"?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/achievements/${encodeURIComponent(achievementName)}`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error('Failed to delete achievement');

            this.showSuccess(`Achievement "${achievementName}" has been deleted.`);
            this.loadAchievements(); // Reload the achievements list
            
        } catch (error) {
            console.error('Error deleting achievement:', error);
            this.showError('Failed to delete achievement.');
        }
    }

    async loadSkills() {
        try {
            const response = await fetch('/api/skills');
            if (!response.ok) throw new Error('Failed to load skills');
            
            const skills = await response.json();
            this.renderSkills(skills);
        } catch (error) {
            console.error('Error loading skills:', error);
            this.showError('Failed to load skills.');
        }
    }

    renderSkills(skills) {
        const container = document.getElementById('skills-list');
        
        if (skills.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 2rem; color: #7f8c8d;">
                    <div class="icon">🛠️</div>
                    <p>No skills found</p>
                </div>
            `;
            return;
        }

        container.innerHTML = skills.map(skill => `
            <div class="skill-item" style="
                background: white;
                padding: 1rem;
                border-radius: 8px;
                border: 1px solid #ddd;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            ">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span style="font-size: 1.2rem;">🛠️</span>
                    <span style="font-weight: 500;">${skill}</span>
                </div>
                <button class="action-btn btn-danger" onclick="adminPanel.deleteSkill('${skill}')">
                    Delete
                </button>
            </div>
        `).join('');
    }

    async addSkill() {
        const input = document.getElementById('new-skill-input');
        const resultDiv = document.getElementById('add-skill-result');
        const skillName = input.value.trim();

        if (!skillName) {
            this.showError('Please enter a skill name.');
            return;
        }

        try {
            const response = await fetch('/api/skills', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ name: skillName })
            });

            if (!response.ok) throw new Error('Failed to add skill');

            resultDiv.innerHTML = `
                <div class="alert alert-success">
                    <strong>Success!</strong> Skill "${skillName}" has been added.
                </div>
            `;

            input.value = '';
            this.loadSkills(); // Reload the skills list
            
        } catch (error) {
            console.error('Error adding skill:', error);
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <strong>Error!</strong> Failed to add skill.
                </div>
            `;
        }
    }

    async deleteSkill(skillName) {
        if (!confirm(`Are you sure you want to delete the skill "${skillName}"?\n\nThis will remove the skill from all crew members who have it.`)) {
            return;
        }

        try {
            const response = await fetch(`/api/skills/${encodeURIComponent(skillName)}`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error('Failed to delete skill');

            this.showSuccess(`Skill "${skillName}" has been deleted.`);
            this.loadSkills(); // Reload the skills list
            
        } catch (error) {
            console.error('Error deleting skill:', error);
            this.showError('Failed to delete skill.');
        }
    }

    showModal(modalId) {
        document.getElementById(modalId).style.display = 'block';
    }

    closeModal(modalId) {
        document.getElementById(modalId).style.display = 'none';
        this.selectedUser = null;
        this.selectedResource = null;
    }

    showSuccess(message) {
        this.showAlert(message, 'success');
    }

    showError(message) {
        this.showAlert(message, 'error');
    }

    showAlert(message, type) {
        // Remove existing alerts
        document.querySelectorAll('.alert').forEach(alert => {
            if (!alert.closest('#migration-result')) {
                alert.remove();
            }
        });
        
        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.textContent = message;
        
        document.querySelector('.admin-container').insertBefore(
            alert, 
            document.querySelector('.admin-nav')
        );
        
        // Auto-hide after 5 seconds
        setTimeout(() => {
            alert.remove();
        }, 5000);
    }

    formatDate(dateString) {
        if (!dateString) return 'Unknown';
        try {
            return new Date(dateString).toLocaleDateString();
        } catch {
            return 'Invalid Date';
        }
    }

    truncateText(text, maxLength) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    async removeOwner(resourceType, resourceId, ownerId, event) {
        event.stopPropagation(); // Prevent the button from triggering the owner pill's onclick
        const confirm = window.confirm(`Are you sure you want to remove this owner? This action cannot be undone.`);
        if (!confirm) return;

        try {
            const response = await fetch('/api/admin/resources/remove-owner', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `resource_type=${resourceType}&resource_id=${encodeURIComponent(resourceId)}&owner_id=${ownerId}`
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }

            const result = await response.json();
            this.showSuccess(result.message);

            // Reload resources and stats
            await this.loadAllResources();
            await this.loadDashboardStats();

        } catch (error) {
            console.error('Error removing owner:', error);
            this.showError(`Failed to remove owner: ${error.message}`);
        }
    }

    // === NOTIFICATION MANAGEMENT ===

    async openUserNotificationSettings(userId, userName) {
        try {
            const response = await fetch(`/api/admin/users/${userId}/notifications`);
            if (!response.ok) throw new Error('Failed to load user notifications');
            
            const data = await response.json();
            this.showUserNotificationModal(data.user, data.devices);
        } catch (error) {
            console.error('Error loading user notifications:', error);
            this.showError('Failed to load user notification settings.');
        }
    }

    showUserNotificationModal(user, devices) {
        const devicesHtml = devices.length > 0 ? `
            <table class="notification-devices-table">
                <thead>
                    <tr>
                        <th>Device</th>
                        <th>Album Created</th>
                        <th>Crew Added</th>
                        <th>Meme Uploaded</th>
                        <th>System Announcements</th>
                        <th>Last Used</th>
                    </tr>
                </thead>
                <tbody>
                    ${devices.map(device => `
                        <tr>
                            <td>
                                <div class="device-info">
                                    <span class="device-icon">${this.getDeviceIcon(device.platform)}</span>
                                    <div>
                                        <div style="font-weight: 500;">${device.browser_name}</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">${device.platform}</div>
                                    </div>
                                </div>
                            </td>
                            <td>
                                <div class="notification-toggle">
                                    <input type="checkbox" 
                                           ${device.notification_preferences.album_created ? 'checked' : ''}
                                           onchange="adminPanel.updateUserNotificationPreference('${user.id}', '${device.device_id}', 'album_created', this.checked)">
                                </div>
                            </td>
                            <td>
                                <div class="notification-toggle">
                                    <input type="checkbox" 
                                           ${device.notification_preferences.crew_member_added ? 'checked' : ''}
                                           onchange="adminPanel.updateUserNotificationPreference('${user.id}', '${device.device_id}', 'crew_member_added', this.checked)">
                                </div>
                            </td>
                            <td>
                                <div class="notification-toggle">
                                    <input type="checkbox" 
                                           ${device.notification_preferences.meme_uploaded ? 'checked' : ''}
                                           onchange="adminPanel.updateUserNotificationPreference('${user.id}', '${device.device_id}', 'meme_uploaded', this.checked)">
                                </div>
                            </td>
                            <td>
                                <div class="notification-toggle">
                                    <input type="checkbox" 
                                           ${device.notification_preferences.system_announcements ? 'checked' : ''}
                                           onchange="adminPanel.updateUserNotificationPreference('${user.id}', '${device.device_id}', 'system_announcements', this.checked)">
                                </div>
                            </td>
                            <td>${this.formatDate(device.last_used || device.created_at)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        ` : `
            <div class="empty-state" style="padding: 2rem; text-align: center;">
                <div class="icon">📱</div>
                <p>No notification devices found for this user</p>
                <p style="color: #7f8c8d; font-size: 0.9rem;">The user hasn't enabled notifications on any devices yet.</p>
            </div>
        `;

        const modalHtml = `
            <div class="user-notification-modal" onclick="this.remove()">
                <div class="user-notification-modal-content" onclick="event.stopPropagation()">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                        <h3>Notification Settings for ${user.name}</h3>
                        <button onclick="this.closest('.user-notification-modal').remove()" 
                                style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">&times;</button>
                    </div>
                    <p style="color: #7f8c8d; margin-bottom: 1.5rem;">
                        Manage notification preferences for each of ${user.name}'s devices. 
                        Changes take effect immediately.
                    </p>
                    ${devicesHtml}
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
    }

    async updateUserNotificationPreference(userId, deviceId, notificationType, isEnabled) {
        try {
            // Get current preferences for this device
            const response = await fetch(`/api/admin/users/${userId}/notifications`);
            if (!response.ok) throw new Error('Failed to fetch current preferences');
            
            const data = await response.json();
            const device = data.devices.find(d => d.device_id === deviceId);
            
            if (!device) {
                throw new Error('Device not found');
            }

            // Update the specific preference
            const updatedPreferences = {
                ...device.notification_preferences,
                [notificationType]: isEnabled
            };

            // Send updated preferences to server
            const updateResponse = await fetch(`/api/admin/users/${userId}/notifications/${deviceId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(updatedPreferences)
            });

            if (!updateResponse.ok) {
                throw new Error('Failed to update preferences');
            }

            console.log(`✅ Admin updated ${notificationType} preference for user ${userId}`);

        } catch (error) {
            console.error('Error updating user notification preference:', error);
            this.showError('Failed to update notification preference');
            
            // Revert checkbox state on error
            const modal = document.querySelector('.user-notification-modal');
            if (modal) {
                const checkbox = modal.querySelector(`input[onchange*="${notificationType}"]`);
                if (checkbox) {
                    checkbox.checked = !isEnabled;
                }
            }
        }
    }

    async debugNotifications() {
        console.log('🔍 Starting notification debugging...');
        
        if (!window.notificationsManager) {
            console.error('❌ NotificationsManager not available');
            this.showError('NotificationsManager not available');
            return;
        }

        try {
            // Get diagnostics
            const diagnostics = await window.notificationsManager.getNotificationDiagnostics();
            
            // Log service worker state
            await window.notificationsManager.logServiceWorkerState();

            // Check browser focus state
            await window.notificationsManager.checkIfBrowserFocused();
            
            // Clear any existing notifications that might be stuck
            const clearedCount = await window.notificationsManager.clearAllNotifications();
            if (clearedCount > 0) {
                console.log(`🗑️ Cleared ${clearedCount} existing notifications`);
            }
            
            // Test notification display
            const testPassed = await window.notificationsManager.testNotificationDisplay();
            
            if (testPassed) {
                this.showSuccess('✅ Test notification sent - check if you see it!');
            } else {
                this.showError('❌ Test notification failed - check console for details');
            }

            // Display summary
            const summary = [
                `Supported: ${diagnostics.supported}`,
                `Permission: ${diagnostics.permission}`,
                `Service Worker: ${diagnostics.serviceWorkerReady}`,
                `VAPID Key: ${diagnostics.vapidKeyLoaded}`,
                `Subscription: ${diagnostics.subscriptionActive}`,
                `Enabled: ${diagnostics.enabled}`,
                `Cleared old notifications: ${clearedCount}`
            ].join('\n');

            console.log('📋 Diagnostics Summary:\n' + summary);
            
        } catch (error) {
            console.error('❌ Debug failed:', error);
            this.showError('Debug failed: ' + error.message);
        }
    }

    getDeviceIcon(platform) {
        const platformLower = platform.toLowerCase();
        if (platformLower.includes('windows')) return '🖥️';
        if (platformLower.includes('mac')) return '💻';
        if (platformLower.includes('android')) return '📱';
        if (platformLower.includes('ios') || platformLower.includes('iphone')) return '📱';
        if (platformLower.includes('linux')) return '🐧';
        return '📱';
    }

    setupNotificationsTab() {
        // Setup system notification form
        const form = document.getElementById('system-notification-form');
        const targetSelect = document.getElementById('notification-target');
        const specificUsersGroup = document.getElementById('specific-users-group');
        const specificUsersSelect = document.getElementById('specific-users');

        // Populate specific users dropdown
        specificUsersSelect.innerHTML = this.users.map(user => 
            `<option value="${user.id}">${user.name} (${user.email})</option>`
        ).join('');

        // Show/hide specific users dropdown based on target selection
        targetSelect.addEventListener('change', () => {
            specificUsersGroup.style.display = targetSelect.value === 'specific' ? 'block' : 'none';
        });

        // Handle form submission
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendSystemNotification();
        });
    }

    async sendSystemNotification() {
        const form = document.getElementById('system-notification-form');
        const formData = new FormData(form);
        
        const title = formData.get('title');
        const body = formData.get('body');
        const url = formData.get('url');
        const target = formData.get('target');
        
        let targetUsers = null;
        
        // Determine target users based on selection
        if (target === 'specific') {
            const specificUsersSelect = document.getElementById('specific-users');
            targetUsers = Array.from(specificUsersSelect.selectedOptions).map(option => option.value);
            
            if (targetUsers.length === 0) {
                this.showError('Please select at least one user for specific targeting.');
                return;
            }
        } else if (target === 'admins') {
            targetUsers = this.users.filter(user => user.role === 'admin').map(user => user.id);
        } else if (target === 'users') {
            targetUsers = this.users.filter(user => user.role === 'user').map(user => user.id);
        }
        // target === 'all' means targetUsers stays null

        const notificationData = {
            title: title,
            body: body,
            url: url || null,
            target_users: targetUsers
        };

        try {
            const response = await fetch('/api/admin/notifications/system', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(notificationData)
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Failed to send notification');
            }

            this.showSuccess(`✅ ${result.message}`);
            
            // Clear the form
            form.reset();
            document.getElementById('specific-users-group').style.display = 'none';

            console.log('System notification sent:', result);

        } catch (error) {
            console.error('Error sending system notification:', error);
            this.showError(`Failed to send notification: ${error.message}`);
        }
    }

    async troubleshootMacOS() {
        console.log('🍎 Starting macOS notification troubleshooting...');
        
        if (!window.notificationsManager) {
            console.error('❌ NotificationsManager not available');
            this.showError('NotificationsManager not available');
            return;
        }

        try {
            await window.notificationsManager.troubleshootMacOSNotifications();
            this.showSuccess('🍎 macOS troubleshooting complete - check console for detailed instructions!');
        } catch (error) {
            console.error('❌ Troubleshooting failed:', error);
            this.showError('Troubleshooting failed: ' + error.message);
        }
    }
}

// Global functions for inline event handlers
window.adminPanel = null;

// Close modal function for inline handlers
window.closeModal = function(modalId) {
    if (window.adminPanel) {
        window.adminPanel.closeModal(modalId);
    }
};

// Initialize admin panel when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.adminPanel = new AdminPanel();
}); 

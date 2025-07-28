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
        
        // Create form data for the API call
        const apiFormData = new FormData();
        apiFormData.append('new_role', newRole);
        
        try {
            const response = await fetch(`/api/admin/users/${this.selectedUser}/role`, {
                method: 'POST',
                body: apiFormData
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

        // Add character counter for text areas
        const bodyTextarea = document.getElementById('notification-body');
        if (bodyTextarea) {
            this.addCharacterCounter(bodyTextarea, 200);
        }

        const titleInput = document.getElementById('notification-title');
        if (titleInput) {
            this.addCharacterCounter(titleInput, 50);
        }

        // Setup file upload functionality
        this.setupFileUploads();

        // Add form validation
        this.setupFormValidation(form);

        // Handle form submission
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendSystemNotification();
        });
    }

    addCharacterCounter(element, maxLength) {
        const formGroup = element.closest('.form-group');
        if (!formGroup) return;

        formGroup.classList.add('char-counter');
        
        const updateCounter = () => {
            const count = element.value.length;
            formGroup.setAttribute('data-count', `${count}/${maxLength}`);
            
            // Update styling based on character count
            if (count > maxLength * 0.9) {
                formGroup.classList.add('warning');
            } else {
                formGroup.classList.remove('warning');
            }
            
            if (count > maxLength) {
                formGroup.classList.add('error');
            } else {
                formGroup.classList.remove('error');
            }
        };

        element.addEventListener('input', updateCounter);
        element.addEventListener('keyup', updateCounter);
        updateCounter(); // Initial count
    }

    setupFormValidation(form) {
        const inputs = form.querySelectorAll('input, textarea, select');
        
        inputs.forEach(input => {
            // Add real-time validation
            input.addEventListener('blur', () => this.validateField(input));
            input.addEventListener('input', () => {
                if (input.closest('.form-group').classList.contains('error')) {
                    this.validateField(input);
                }
            });
        });
    }

    validateField(field) {
        const formGroup = field.closest('.form-group');
        const isRequired = field.hasAttribute('required');
        const isEmpty = !field.value.trim();
        
        // Clear previous validation states
        formGroup.classList.remove('error', 'success');
        
        if (isRequired && isEmpty) {
            formGroup.classList.add('error');
            return false;
        }
        
        // Check specific field validations
        if (field.type === 'url' && field.value && !this.isValidUrl(field.value)) {
            formGroup.classList.add('error');
            return false;
        }
        
        if (field.id === 'notification-title' && field.value.length > 50) {
            formGroup.classList.add('error');
            return false;
        }
        
        if (field.id === 'notification-body' && field.value.length > 200) {
            formGroup.classList.add('error');
            return false;
        }
        
        if (field.value) {
            formGroup.classList.add('success');
        }
        
        return true;
    }

    isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }

    async sendSystemNotification() {
        const form = document.getElementById('system-notification-form');
        const submitBtn = form.querySelector('button[type="submit"]');
        const formData = new FormData(form);
        
        // Validate form before submission
        const isValid = this.validateForm(form);
        if (!isValid) {
            this.showNotificationToast('Please fix the form errors before submitting', 'error');
            return;
        }
        
        // Show loading state
        this.setButtonLoading(submitBtn, true);
        
        try {
            // Build comprehensive notification data
            const notificationData = await this.buildNotificationData(form, false);
            
            // Determine target users
            const target = formData.get('target');
            let targetUsers = null;
            
            if (target === 'specific') {
                const specificUsersSelect = document.getElementById('specific-users');
                targetUsers = Array.from(specificUsersSelect.selectedOptions).map(option => option.value);
                
                if (targetUsers.length === 0) {
                    this.showNotificationToast('Please select at least one user for specific targeting.', 'error');
                    this.setButtonLoading(submitBtn, false);
                    return;
                }
            } else if (target === 'admins') {
                targetUsers = this.users.filter(user => user.role === 'admin').map(user => user.id);
            } else if (target === 'users') {
                targetUsers = this.users.filter(user => user.role === 'user').map(user => user.id);
            }
            // target === 'all' means targetUsers stays null

            // Prepare payload for backend
            const payload = {
                title: notificationData.title,
                body: notificationData.body,
                icon: notificationData.icon,
                image: notificationData.image,
                badge: notificationData.badge,
                tag: notificationData.tag,
                url: notificationData.data.url,
                target_users: targetUsers,
                // Advanced options
                lang: notificationData.lang,
                dir: notificationData.dir,
                timestamp: notificationData.timestamp,
                require_interaction: notificationData.requireInteraction,
                silent: notificationData.silent,
                renotify: notificationData.renotify,
                vibrate: notificationData.vibrate,
                actions: notificationData.actions
            };

            const response = await fetch('/api/admin/notifications/system', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Failed to send notification');
            }

            this.showNotificationToast(`✅ ${result.message}`, 'success');
            
            // Clear and reset the form
            form.reset();
            document.getElementById('specific-users-group').style.display = 'none';
            this.clearFormValidation(form);
            this.clearFileUploads();

            console.log('System notification sent:', result);

        } catch (error) {
            console.error('Error sending system notification:', error);
            this.showNotificationToast(`Failed to send notification: ${error.message}`, 'error');
        } finally {
            this.setButtonLoading(submitBtn, false);
        }
    }

    clearFileUploads() {
        // Clear file previews
        const previews = ['icon-preview', 'image-preview'];
        previews.forEach(previewId => {
            const preview = document.getElementById(previewId);
            if (preview) {
                // Clear stored image URL
                if (preview.dataset.imageUrl) {
                    delete preview.dataset.imageUrl;
                }
                preview.style.display = 'none';
                preview.innerHTML = '';
            }
        });

        // Reset upload areas
        const uploadAreas = document.querySelectorAll('.file-upload-area');
        uploadAreas.forEach(area => {
            area.classList.remove('success', 'error');
            const uploadText = area.querySelector('.upload-text');
            if (uploadText) {
                uploadText.textContent = uploadText.getAttribute('data-original-text') || 'Click to upload or drag & drop';
            }
        });

        // Reset advanced options
        const advancedOptions = document.getElementById('advanced-options');
        const expandTitle = document.querySelector('.section-title.expandable');
        if (advancedOptions.classList.contains('expanded')) {
            advancedOptions.classList.remove('expanded');
            expandTitle.classList.remove('expanded');
        }
    }

    validateForm(form) {
        const inputs = form.querySelectorAll('input[required], textarea[required], select[required]');
        let isValid = true;
        
        inputs.forEach(input => {
            if (!this.validateField(input)) {
                isValid = false;
            }
        });
        
        return isValid;
    }

    clearFormValidation(form) {
        const formGroups = form.querySelectorAll('.form-group');
        formGroups.forEach(group => {
            group.classList.remove('error', 'success', 'warning');
        });
    }

    setButtonLoading(button, isLoading) {
        if (isLoading) {
            button.classList.add('loading');
            button.disabled = true;
            button.dataset.originalText = button.textContent;
            button.textContent = 'Sending...';
        } else {
            button.classList.remove('loading');
            button.disabled = false;
            if (button.dataset.originalText) {
                button.textContent = button.dataset.originalText;
                delete button.dataset.originalText;
            }
        }
    }

    showNotificationToast(message, type = 'info') {
        // Remove existing toasts
        document.querySelectorAll('.notification-toast').forEach(toast => toast.remove());
        
        const toast = document.createElement('div');
        toast.className = `notification-toast ${type}`;
        toast.textContent = message;
        
        document.body.appendChild(toast);
        
        // Show toast with animation
        setTimeout(() => toast.classList.add('show'), 100);
        
        // Auto-hide after 5 seconds
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 400);
        }, 5000);
    }

    async openUserNotificationSettings(userId, userName) {
        try {
            // Show loading state
            this.showNotificationToast('Loading notification settings...', 'info');
            
            const response = await fetch(`/api/admin/users/${userId}/notifications`);
            if (!response.ok) throw new Error('Failed to load user notifications');
            
            const data = await response.json();
            this.showUserNotificationModal(data.user, data.devices);
        } catch (error) {
            console.error('Error loading user notifications:', error);
            this.showNotificationToast('Failed to load user notification settings.', 'error');
        }
    }

    showUserNotificationModal(user, devices) {
        // Remove any existing modal
        document.querySelectorAll('.user-notification-modal').forEach(modal => modal.remove());
        
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
                                    <div class="device-name">
                                        <span class="device-icon">${this.getDeviceIcon(device.platform)}</span>
                                        ${device.browser_name}
                                    </div>
                                    <div class="device-platform">${device.platform}</div>
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
                    <div class="modal-header">
                        <h3>Notification Settings for ${user.name}</h3>
                        <button onclick="this.closest('.user-notification-modal').remove()">&times;</button>
                    </div>
                    <div style="padding: 2rem;">
                        <p style="color: #888; margin-bottom: 1.5rem;">
                            Manage notification preferences for each of ${user.name}'s devices. 
                            Changes take effect immediately.
                        </p>
                        ${devicesHtml}
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
        // Show modal with animation
        const modal = document.querySelector('.user-notification-modal');
        setTimeout(() => modal.classList.add('show'), 100);
    }

    async updateUserNotificationPreference(userId, deviceId, notificationType, isEnabled) {
        try {
            // Show immediate visual feedback
            const checkbox = event.target;
            const toggle = checkbox.closest('.notification-toggle');
            toggle.style.opacity = '0.7';
            
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

            // Show success feedback
            toggle.style.opacity = '1';
            toggle.style.transform = 'scale(1.05)';
            setTimeout(() => {
                toggle.style.transform = 'scale(1)';
            }, 200);

            console.log(`✅ Admin updated ${notificationType} preference for user ${userId}`);

        } catch (error) {
            console.error('Error updating user notification preference:', error);
            this.showNotificationToast('Failed to update notification preference', 'error');
            
            // Revert checkbox state on error
            const modal = document.querySelector('.user-notification-modal');
            if (modal) {
                const checkbox = modal.querySelector(`input[onchange*="${notificationType}"]`);
                if (checkbox) {
                    checkbox.checked = !isEnabled;
                }
            }
            
            // Reset visual feedback
            const toggle = event.target.closest('.notification-toggle');
            if (toggle) {
                toggle.style.opacity = '1';
                toggle.style.transform = 'scale(1)';
            }
        }
    }

    async debugNotifications() {
        console.log('🔍 Starting notification debugging...');
        
        // Show loading state
        const debugBtn = document.querySelector('.btn-secondary');
        this.setButtonLoading(debugBtn, true);
        
        if (!window.notificationsManager) {
            console.error('❌ NotificationsManager not available');
            this.showNotificationToast('NotificationsManager not available', 'error');
            this.setButtonLoading(debugBtn, false);
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
                this.showNotificationToast('✅ Test notification sent - check if you see it!', 'success');
            } else {
                this.showNotificationToast('❌ Test notification failed - check console for details', 'error');
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
            this.showNotificationToast('Debug failed: ' + error.message, 'error');
        } finally {
            this.setButtonLoading(debugBtn, false);
        }
    }

    async troubleshootMacOS() {
        console.log('🍎 Starting macOS notification troubleshooting...');
        
        // Show loading state
        const troubleshootBtn = document.querySelector('.btn-warning');
        this.setButtonLoading(troubleshootBtn, true);
        
        if (!window.notificationsManager) {
            console.error('❌ NotificationsManager not available');
            this.showNotificationToast('NotificationsManager not available', 'error');
            this.setButtonLoading(troubleshootBtn, false);
            return;
        }

        try {
            await window.notificationsManager.troubleshootMacOSNotifications();
            this.showNotificationToast('🍎 macOS troubleshooting complete - check console for detailed instructions!', 'success');
        } catch (error) {
            console.error('❌ Troubleshooting failed:', error);
            this.showNotificationToast('Troubleshooting failed: ' + error.message, 'error');
        } finally {
            this.setButtonLoading(troubleshootBtn, false);
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

    // ===== ADVANCED NOTIFICATION FEATURES =====

    setupFileUploads() {
        // Setup icon upload
        this.setupFileUpload('notification-icon', 'icon-preview', {
            maxSize: 2 * 1024 * 1024, // 2MB
            allowedTypes: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
            recommended: '192x192px'
        });

        // Setup image upload  
        this.setupFileUpload('notification-image', 'image-preview', {
            maxSize: 5 * 1024 * 1024, // 5MB
            allowedTypes: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
            recommended: '360x240px'
        });
    }

    setupFileUpload(inputId, previewId, options) {
        const input = document.getElementById(inputId);
        const uploadArea = input.nextElementSibling;
        const preview = document.getElementById(previewId);

        // File input change handler
        input.addEventListener('change', (e) => {
            this.handleFileSelect(e.target.files[0], uploadArea, preview, options);
        });

        // Drag and drop handlers
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) {
                input.files = e.dataTransfer.files;
                this.handleFileSelect(file, uploadArea, preview, options);
            }
        });
    }

    async handleFileSelect(file, uploadArea, preview, options) {
        // Reset states
        uploadArea.classList.remove('error', 'success');

        if (!file) return;

        // Validate file type
        if (!options.allowedTypes.includes(file.type)) {
            this.showFileError(uploadArea, `Please select a valid image file (${options.allowedTypes.map(t => t.split('/')[1]).join(', ')})`);
            return;
        }

        // Validate file size
        if (file.size > options.maxSize) {
            this.showFileError(uploadArea, `File size must be less than ${this.formatFileSize(options.maxSize)}`);
            return;
        }

        // Show uploading state
        uploadArea.classList.add('uploading');
        uploadArea.querySelector('.upload-text').textContent = `⏳ Uploading ${file.name}...`;

        try {
            // Upload image to server
            const imageUrl = await this.uploadImageToServer(file);
            
            // Show success state
            uploadArea.classList.remove('uploading');
            uploadArea.classList.add('success');
            uploadArea.querySelector('.upload-text').textContent = `✅ ${file.name} uploaded`;

            // Create preview with server URL
            this.createFilePreviewFromUrl(file, imageUrl, preview);
            
        } catch (error) {
            console.error('Failed to upload image:', error);
            uploadArea.classList.remove('uploading');
            this.showFileError(uploadArea, `Upload failed: ${error.message}`);
        }
    }

    async uploadImageToServer(file) {
        const formData = new FormData();
        formData.append('image', file);

        const response = await fetch('/api/admin/notifications/upload-image', {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Upload failed');
        }

        const result = await response.json();
        return result.image_url;
    }

    showFileError(uploadArea, message) {
        uploadArea.classList.add('error');
        uploadArea.querySelector('.upload-text').textContent = `❌ ${message}`;
        
        // Reset after 3 seconds
        setTimeout(() => {
            uploadArea.classList.remove('error');
            uploadArea.querySelector('.upload-text').textContent = uploadArea.getAttribute('data-original-text') || 'Click to upload or drag & drop';
        }, 3000);
    }

    createFilePreview(file, preview) {
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.innerHTML = `
                <img src="${e.target.result}" alt="Preview">
                <div class="file-preview-info">
                    <div class="file-preview-name">${file.name}</div>
                    <div class="file-preview-size">${this.formatFileSize(file.size)}</div>
                </div>
                <button type="button" class="file-preview-remove" onclick="adminPanel.removeFilePreview('${preview.id}')">
                    🗑️
                </button>
            `;
            preview.style.display = 'flex';
        };
        reader.readAsDataURL(file);
    }

    createFilePreviewFromUrl(file, imageUrl, preview) {
        // Store the image URL for later use
        preview.dataset.imageUrl = imageUrl;
        
        preview.innerHTML = `
            <img src="${imageUrl}" alt="Preview">
            <div class="file-preview-info">
                <div class="file-preview-name">${file.name}</div>
                <div class="file-preview-size">${this.formatFileSize(file.size)}</div>
            </div>
            <button type="button" class="file-preview-remove" onclick="adminPanel.removeFilePreview('${preview.id}')">
                🗑️
            </button>
        `;
        preview.style.display = 'flex';
    }

    removeFilePreview(previewId) {
        const preview = document.getElementById(previewId);
        const input = preview.parentElement.querySelector('input[type="file"]');
        const uploadArea = preview.parentElement.querySelector('.file-upload-area');
        
        // Clear file input
        input.value = '';
        
        // Clear stored image URL
        if (preview.dataset.imageUrl) {
            delete preview.dataset.imageUrl;
        }
        
        // Hide preview
        preview.style.display = 'none';
        preview.innerHTML = '';
        
        // Reset upload area
        uploadArea.classList.remove('success', 'error');
        uploadArea.querySelector('.upload-text').textContent = uploadArea.getAttribute('data-original-text') || 'Click to upload or drag & drop';
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    toggleAdvancedOptions() {
        const advancedOptions = document.getElementById('advanced-options');
        const expandTitle = document.querySelector('.section-title.expandable');
        
        if (advancedOptions.classList.contains('expanded')) {
            advancedOptions.classList.remove('expanded');
            expandTitle.classList.remove('expanded');
        } else {
            advancedOptions.classList.add('expanded');
            expandTitle.classList.add('expanded');
        }
    }

    setVibrationPreset(value) {
        const patternInput = document.getElementById('vibration-pattern');
        if (value) {
            patternInput.value = value;
        }
    }

    async previewNotification() {
        const form = document.getElementById('system-notification-form');
        
        // Validate basic fields first
        const title = form.title.value.trim();
        const body = form.body.value.trim();
        
        if (!title || !body) {
            this.showNotificationToast('Please fill in title and message to preview', 'warning');
            return;
        }

        try {
            // Build notification data from form
            const notificationData = await this.buildNotificationData(form, true); // preview mode
            
            // Show preview using service worker
            if (window.notificationsManager && window.notificationsManager.registration) {
                await window.notificationsManager.registration.showNotification(
                    notificationData.title,
                    {
                        body: notificationData.body,
                        icon: notificationData.icon,
                        image: notificationData.image,
                        badge: notificationData.badge,
                        tag: 'admin-preview',
                        requireInteraction: notificationData.requireInteraction,
                        silent: notificationData.silent,
                        actions: notificationData.actions || [],
                        vibrate: notificationData.vibrate,
                        data: { ...notificationData.data, preview: true }
                    }
                );
                
                this.showNotificationToast('🎉 Preview notification sent! Check your notifications.', 'success');
            } else {
                this.showNotificationToast('Notifications not available for preview', 'error');
            }
            
        } catch (error) {
            console.error('Preview error:', error);
            this.showNotificationToast(`Preview failed: ${error.message}`, 'error');
        }
    }

    async buildNotificationData(form, isPreview = false) {
        const formData = new FormData(form);
        const data = {
            title: formData.get('title'),
            body: formData.get('body'),
            icon: '/static/favicon/android-chrome-192x192.png', // default
            badge: '/static/favicon/favicon-32x32.png',
            tag: formData.get('tag') || (isPreview ? 'admin-preview' : `admin-${Date.now()}`),
            requireInteraction: formData.get('require_interaction') === 'on',
            silent: formData.get('silent') === 'on',
            renotify: formData.get('renotify') === 'on',
            data: {
                url: formData.get('url') || '/',
                type: 'admin_notification',
                timestamp: Date.now()
            }
        };

        // Add custom timestamp if provided
        const customTimestamp = formData.get('timestamp');
        if (customTimestamp) {
            data.timestamp = new Date(customTimestamp).getTime();
        }

        // Add language and direction
        const lang = formData.get('lang');
        if (lang) data.lang = lang;
        
        const dir = formData.get('dir');
        if (dir && dir !== 'auto') data.dir = dir;

        // Handle custom icon upload (get URL from preview)
        const iconPreview = document.getElementById('icon-preview');
        if (iconPreview && iconPreview.dataset.imageUrl) {
            data.icon = iconPreview.dataset.imageUrl;
        }

        // Handle custom image upload (get URL from preview)
        const imagePreview = document.getElementById('image-preview');
        if (imagePreview && imagePreview.dataset.imageUrl) {
            data.image = imagePreview.dataset.imageUrl;
        }

        // Handle action buttons
        const actions = [];
        for (let i = 1; i <= 2; i++) {
            const actionTitle = formData.get(`action_${i}_title`);
            const actionUrl = formData.get(`action_${i}_url`);
            const actionIcon = formData.get(`action_${i}_icon`);
            
            if (actionTitle && actionTitle.trim()) {
                const action = {
                    action: `action_${i}`,
                    title: actionTitle.trim(),
                    icon: actionIcon || undefined
                };
                
                if (actionUrl && actionUrl.trim()) {
                    action.data = { url: actionUrl.trim() };
                }
                
                actions.push(action);
            }
        }
        
        if (actions.length > 0) {
            data.actions = actions;
        }

        // Handle vibration pattern
        const vibrationPattern = formData.get('vibrate');
        if (vibrationPattern && vibrationPattern.trim()) {
            try {
                const pattern = vibrationPattern.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v));
                if (pattern.length > 0) {
                    data.vibrate = pattern;
                }
            } catch (e) {
                console.warn('Invalid vibration pattern:', vibrationPattern);
            }
        }

        return data;
    }

    async fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
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

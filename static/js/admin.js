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
        await this.loadUnownedResources();
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

        // Assign form submission
        document.getElementById('assignForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.assignResource();
        });

        // Migration button
        document.getElementById('migrate-btn').addEventListener('click', () => {
            this.migrateResources();
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
            this.loadUnownedResources();
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
                        <img src="${user.picture || '/static/photos/default-avatar.png'}" 
                             alt="${user.name}" 
                             style="width: 32px; height: 32px; border-radius: 50%;">
                        ${user.name}
                    </div>
                </td>
                <td>${user.email}</td>
                <td>
                    <span class="role-badge role-${user.role}">
                        ${user.role.toUpperCase()}
                    </span>
                </td>
                <td>${user.owned_albums}</td>
                <td>${user.owned_crew_members}</td>
                <td>${this.formatDate(user.created_at)}</td>
                <td>
                    <button class="action-btn btn-primary" 
                            onclick="adminPanel.openRoleModal('${user.id}', '${user.role}')">
                        Change Role
                    </button>
                </td>
            </tr>
        `).join('');
    }

    async loadUnownedResources() {
        try {
            const response = await fetch('/api/admin/resources/unowned');
            if (!response.ok) throw new Error('Failed to load resources');
            
            const data = await response.json();
            this.resources = [...data.albums, ...data.crew_members];
            this.renderResourcesTable();
        } catch (error) {
            console.error('Error loading resources:', error);
            this.showError('Failed to load unowned resources.');
        }
    }

    renderResourcesTable() {
        const tbody = document.getElementById('resources-tbody');
        
        if (this.resources.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="empty-state">
                        <div class="icon">📁</div>
                        <p>No unowned resources found</p>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = this.resources.map(resource => `
            <tr>
                <td>
                    <span class="role-badge ${resource.type === 'album' ? 'role-user' : 'role-admin'}">
                        ${resource.type === 'album' ? 'ALBUM' : 'CREW'}
                    </span>
                </td>
                <td>${resource.title || resource.name}</td>
                <td style="font-family: monospace; font-size: 0.8rem;">
                    ${this.truncateText(resource.id, 40)}
                </td>
                <td>${this.formatDate(resource.created_at)}</td>
                <td>
                    <button class="action-btn btn-success" 
                            onclick="adminPanel.openAssignModal('${resource.type}', '${resource.id}')">
                        Assign
                    </button>
                </td>
            </tr>
        `).join('');
    }

    openRoleModal(userId, currentRole) {
        this.selectedUser = userId;
        document.getElementById('userRole').value = currentRole;
        this.showModal('roleModal');
    }

    async openAssignModal(resourceType, resourceId) {
        this.selectedResource = { type: resourceType, id: resourceId };
        
        // Populate user dropdown
        const userSelect = document.getElementById('targetUser');
        userSelect.innerHTML = this.users.map(user => 
            `<option value="${user.id}">${user.name} (${user.email})</option>`
        ).join('');
        
        this.showModal('assignModal');
    }

    async updateUserRole() {
        if (!this.selectedUser) return;
        
        const formData = new FormData(document.getElementById('roleForm'));
        const newRole = formData.get('role');
        
        try {
            const response = await fetch(`/api/admin/users/${this.selectedUser}/role`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `new_role=${newRole}`
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

    async assignResource() {
        if (!this.selectedResource) return;
        
        const formData = new FormData(document.getElementById('assignForm'));
        const targetUserId = formData.get('targetUser');
        
        try {
            const response = await fetch('/api/admin/resources/assign', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `resource_type=${this.selectedResource.type}&resource_id=${encodeURIComponent(this.selectedResource.id)}&target_user_id=${targetUserId}`
            });
            
            if (!response.ok) throw new Error('Failed to assign resource');
            
            const result = await response.json();
            this.showSuccess(result.message);
            this.closeModal('assignModal');
            
            // Reload resources and stats
            await this.loadUnownedResources();
            await this.loadDashboardStats();
            
        } catch (error) {
            console.error('Error assigning resource:', error);
            this.showError('Failed to assign resource.');
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
            await this.loadUnownedResources();
            
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

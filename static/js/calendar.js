/**
 * Calendar Grid Component
 * Displays a month view with dates as rows (Y-axis) and 24 hours as columns (X-axis)
 * Shows approved (green), pending (yellow), and blocked (blue) bookings
 */

class HallCalendar {
  constructor(containerId, hallId) {
    this.container = document.getElementById(containerId);
    this.hallId = hallId;
    this.currentDate = new Date();
    this.bookings = [];
    this.tooltips = [];
    window.addEventListener('resize', () => {
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => this.render(), 120);
    });
  }

  async init() {
    await this.loadBookings();
    this.render();
  }

  async loadBookings() {
    const year = this.currentDate.getFullYear();
    const month = this.currentDate.getMonth() + 1;
    
    try {
      const res = await fetch(`/api/halls/${this.hallId}/bookings/month?year=${year}&month=${month}`);
      const data = await res.json();
      this.bookings = data.bookings || [];
    } catch (err) {
      console.error('Failed to load bookings:', err);
      this.bookings = [];
    }
  }

  changeMonth(delta) {
    this.currentDate.setMonth(this.currentDate.getMonth() + delta);
    this.init();
  }

  getDaysInMonth() {
    const year = this.currentDate.getFullYear();
    const month = this.currentDate.getMonth();
    return new Date(year, month + 1, 0).getDate();
  }

  getMonthName() {
    return this.currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  }

  parseTime(timeStr) {
    const parts = timeStr.split(':').map(Number);
    return parts[0] + (parts[1] || 0) / 60;
  }

  getBookingsForDay(day) {
    const year = this.currentDate.getFullYear();
    const month = this.currentDate.getMonth() + 1;
    const dateStr = `${year}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
    
    return this.bookings.filter(b => b.booking_date === dateStr);
  }

  render() {
    const daysInMonth = this.getDaysInMonth();
    
    // Clean up existing tooltips
    this.tooltips.forEach(t => t.dispose());
    this.tooltips = [];

    const series = new Map();
    this.bookings.forEach(booking => {
      if (booking.can_delete && booking.booking_type === 'blocked' && booking.event_group_id) {
        const item = series.get(booking.event_group_id) || { label: booking.message || booking.requester_name || 'Blocked event', count: 0 };
        item.count += 1;
        series.set(booking.event_group_id, item);
      }
    });
    
    // Fit the month into the available viewport height while retaining legible rows.
    const rowHeight = Math.max(20, Math.min(24, Math.floor((window.innerHeight - 240) / daysInMonth)));
    
    let html = `
      <div class="calendar-month-nav">
        <button class="btn btn-sm btn-outline-primary" onclick="calendar.changeMonth(-1)">
          <i class="bi bi-chevron-left"></i> Previous
        </button>
        <strong>${this.getMonthName()}</strong>
        <button class="btn btn-sm btn-outline-primary" onclick="calendar.changeMonth(1)">
          Next <i class="bi bi-chevron-right"></i>
        </button>
      </div>
      
      <div class="calendar-legend">
        <div class="calendar-legend-item">
          <div class="calendar-legend-box legend-approved"></div>
          <span>Approved</span>
        </div>
        <div class="calendar-legend-item">
          <div class="calendar-legend-box legend-pending"></div>
          <span>Pending</span>
        </div>
        <div class="calendar-legend-item">
          <div class="calendar-legend-box legend-blocked"></div>
          <span>Blocked/Reserved</span>
        </div>
      </div>
      ${series.size ? `<div class="calendar-series-list"><strong>Admin-created event series</strong>${[...series.entries()].map(([id, item]) => `
        <div class="calendar-series-item">
          <span>${this.escapeHtml(item.label)} <small class="text-muted">(${item.count} date${item.count === 1 ? '' : 's'} this month)</small></span>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteBlockedEvent('${id}')"><i class="bi bi-trash"></i> Delete entire event</button>
        </div>`).join('')}</div>` : ''}
      
      <div class="calendar-container">
        <table class="calendar-table">
          <thead>
            <tr>
              <th class="calendar-date-header">Date</th>
    `;
    
    // Hour headers (0-23)
    for (let hour = 0; hour < 24; hour++) {
      html += `<th class="calendar-hour-header">${hour.toString().padStart(2, '0')}</th>`;
    }
    
    html += `</tr></thead><tbody>`;
    
    // Date rows
    for (let day = 1; day <= daysInMonth; day++) {
      const dayBookings = this.getBookingsForDay(day);
      html += `<tr style="height: ${rowHeight}px;">`;
      html += `<td class="calendar-date-cell">${day}</td>`;
      
      // One cell spans the 24 hour columns, so booking x positions map to time.
      html += `<td colspan="24" style="padding: 0; position: relative; height: 100%;">
                 <div class="calendar-day-bookings" style="position: relative; width: 100%; height: ${rowHeight}px;">`;
      
      // Add all bookings for this day
      dayBookings.forEach((booking, idx) => {
        const startHour = this.parseTime(booking.start_time);
        const endHour = this.parseTime(booking.end_time);
        const duration = endHour - startHour;
        
        // Assign a separate vertical lane only when bookings overlap.
        
        let statusClass = `status-${booking.status}`;
        if (booking.booking_type === 'blocked') {
          statusClass += ' type-blocked';
        }
        
        const tooltipText = this.formatTooltip(booking);
        
        // Calculate left position and width based on overlapping bookings
        const overlappingBookings = dayBookings.filter(b => {
          const bStart = this.parseTime(b.start_time);
          const bEnd = this.parseTime(b.end_time);
          return !(bEnd <= startHour || bStart >= endHour);
        });
        
        const bookingIndex = overlappingBookings.indexOf(booking);
        const laneCount = overlappingBookings.length;
        const leftPercent = (startHour / 24) * 100;
        const widthPercent = (duration / 24) * 100;
        const laneHeight = 100 / laneCount;
        const topPercent = bookingIndex * laneHeight;
        
        html += `
          <div class="calendar-booking-bar ${statusClass}"
               style="
                 position: absolute;
                 left: ${leftPercent}%;
                 top: calc(${topPercent}% + 2px);
                 width: ${widthPercent}%;
                 height: calc(${laneHeight}% - 4px);
                 z-index: ${10 + idx};
               "
               data-bs-toggle="tooltip"
               data-bs-placement="top"
               title="${this.escapeHtml(tooltipText)}">
            <span class="booking-text">${booking.start_time} - ${booking.end_time}</span>
            ${booking.can_delete ? `<button class="booking-delete" aria-label="Delete booking on ${booking.booking_date}" title="Delete this booking" onclick="event.stopPropagation(); deleteCalendarBooking(${booking.id}, '${booking.booking_date}', '${booking.start_time}')">&times;</button>` : ''}
          </div>
        `;
      });
      
      html += `</div></td>`;
      html += `</tr>`;
    }
    
    html += `</tbody></table></div>`;
    
    this.container.innerHTML = html;
    
    // Initialize Bootstrap tooltips
    setTimeout(() => {
      const tooltipTriggerList = this.container.querySelectorAll('[data-bs-toggle="tooltip"]');
      this.tooltips = [...tooltipTriggerList].map(el => {
        return new bootstrap.Tooltip(el, {
          trigger: 'hover',
          html: false,
          sanitize: true
        });
      });
    }, 100);
  }

  formatTooltip(booking) {
    let parts = [];
    parts.push(booking.requester_name || 'Unknown');
    parts.push(`${booking.start_time}-${booking.end_time}`);
    if (booking.message && booking.message.trim()) {
      parts.push(booking.message);
    }
    return parts.join(' | ');
  }

  escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

// Global calendar instance
let calendar = null;

function initializeCalendar(containerId, hallId) {
  calendar = new HallCalendar(containerId, hallId);
  calendar.init();
  return calendar;
}

async function deleteCalendarBooking(id, date, time) {
  if (!confirm(`Delete this booking on ${date} at ${time}?`)) return;
  const response = await fetch(`/api/bookings/${id}/delete`, { method: 'DELETE' });
  const data = await response.json();
  if (!data.ok) return alert(data.error || 'Could not delete booking');
  calendar.init();
}

async function deleteBlockedEvent(groupId) {
  if (!confirm('Delete every booking occurrence in this admin-created event series?')) return;
  const response = await fetch(`/api/blocked-events/${encodeURIComponent(groupId)}/delete`, { method: 'DELETE' });
  const data = await response.json();
  if (!data.ok) return alert(data.error || 'Could not delete event series');
  alert(`Deleted ${data.deleted_count} event occurrence(s).`);
  calendar.init();
}

const state = {
  bookings: [],
  selectedDate: null,
  datesWithMismatch: [],
};

const calendarGrid = document.getElementById("calendar_grid");
const bookingDetails = document.getElementById("booking_details");
const selectedDateTitle = document.getElementById("selected_date_title");
const selectedDateSummary = document.getElementById("selected_date_summary");
const connectionDot = document.getElementById("connection_dot");
const connectionText = document.getElementById("connection_text");
const lastUpdated = document.getElementById("last_updated");
const padelmatesCount = document.getElementById("padelmates_count");
const playtomicCount = document.getElementById("playtomic_count");
const mismatchCount = document.getElementById("mismatch_count");

fetchBookings();
connectWebSocket();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/service-worker.js").catch(() => {});
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/bookings`);

  ws.addEventListener("open", () => {
    setConnectionState(true, "Live connection");
  });

  ws.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      applyPayload(payload);
    } catch (error) {
      console.warn("Could not parse booking update.", error);
    }
  });

  ws.addEventListener("close", () => {
    setConnectionState(false, "Disconnected. Reconnecting...");
    fetchBookings();
    setTimeout(connectWebSocket, 2000);
  });

  ws.addEventListener("error", () => {
    setConnectionState(false, "WebSocket error");
  });
}

async function fetchBookings() {
  try {
    const response = await fetch("/api/bookings");

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    applyPayload(payload);
  } catch (error) {
    console.warn("Could not fetch booking data.", error);
  }
}

function setConnectionState(isOnline, text) {
  connectionDot.classList.toggle("online", isOnline);
  connectionDot.classList.toggle("offline", !isOnline);
  connectionText.textContent = text;
}

function applyPayload(payload) {
  state.bookings = payload.bookings || [];
  state.datesWithMismatch = payload.dates_with_mismatch || [];

  padelmatesCount.textContent = payload.padelmates_count ?? 0;
  playtomicCount.textContent = payload.playtomic_count ?? 0;
  mismatchCount.textContent = state.datesWithMismatch.length;

  lastUpdated.textContent = `Last updated: ${payload.generated_at}`;

  const availableDates = getAvailableDates(state.bookings);

  if (!state.selectedDate || !availableDates.includes(state.selectedDate)) {
    state.selectedDate = availableDates[0] || null;
  }

  renderCalendar();
  renderDetails();
}

function getAvailableDates(bookings) {
  const dates = [...new Set(bookings.map((booking) => booking.date))]
    .filter(Boolean)
    .sort();

  return dates;
}

function renderCalendar() {
  const bookingsByDate = groupBy(state.bookings, "date");
  const sortedDates = Object.keys(bookingsByDate).sort();

  calendarGrid.innerHTML = "";

  if (sortedDates.length === 0) {
    calendarGrid.innerHTML = `<div class="empty-state">No bookings found yet.</div>`;
    return;
  }

  for (const date of sortedDates) {
    const dateBookings = bookingsByDate[date].sort(compareBookings);
    const hasMismatch = state.datesWithMismatch.includes(date);

    const dayButton = document.createElement("button");
    dayButton.className = "day-card";
    dayButton.classList.toggle("selected", date === state.selectedDate);
    dayButton.classList.toggle("has-mismatch", hasMismatch);

    dayButton.addEventListener("click", () => {
      state.selectedDate = date;
      renderCalendar();
      renderDetails();
    });

    const shortDate = escapeHtml(formatShortDate(date));
    const safeDate = escapeHtml(date);
    const mismatchLabel = hasMismatch
      ? `<span class="mismatch-label">Mismatch</span>`
      : `<span class="ok-label">Matched</span>`;

    dayButton.innerHTML = `
      <div class="day-header">
        <div>
          <strong>${shortDate}</strong>
          <span>${safeDate}</span>
        </div>
        ${mismatchLabel}
      </div>
      <div class="slot-list">
        ${dateBookings.map(renderSlotPill).join("")}
      </div>
    `;

    calendarGrid.appendChild(dayButton);
  }
}

function renderSlotPill(booking) {
  const isMissing = booking.source === "padelmates" && booking.missing_in_playtomic;
  const sourceClass = booking.source === "playtomic" ? "playtomic" : "padelmates";
  const missingClass = isMissing ? "missing" : "";

  return `
    <div class="slot-pill ${sourceClass} ${missingClass}">
      <span>${escapeHtml(booking.start_time)}</span>
      <small>${escapeHtml(booking.court_name)}</small>
    </div>
  `;
}

function renderDetails() {
  if (!state.selectedDate) {
    selectedDateTitle.textContent = "Select a date";
    selectedDateSummary.textContent = "Bookings will appear here.";
    bookingDetails.className = "booking-details empty-state";
    bookingDetails.textContent = "No date selected yet.";
    return;
  }

  const dayBookings = state.bookings
    .filter((booking) => booking.date === state.selectedDate)
    .sort(compareBookings);

  const missingCount = dayBookings.filter(
    (booking) => booking.source === "padelmates" && booking.missing_in_playtomic
  ).length;

  selectedDateTitle.textContent = state.selectedDate;
  selectedDateSummary.textContent = `${dayBookings.length} booking records. ${missingCount} PadelMates bookings missing from Playtomic.`;

  bookingDetails.className = "booking-details";

  if (dayBookings.length === 0) {
    bookingDetails.className = "booking-details empty-state";
    bookingDetails.textContent = "No bookings on this date.";
    return;
  }

  bookingDetails.innerHTML = dayBookings.map(renderBookingCard).join("");
}

function renderBookingCard(booking) {
  const isMissing = booking.source === "padelmates" && booking.missing_in_playtomic;
  const sourceLabel = booking.source === "padelmates" ? "PadelMates" : "Playtomic";

  return `
    <article class="booking-card ${isMissing ? "missing" : ""}">
      <div class="booking-card-header">
        <div>
          <strong>${escapeHtml(booking.start_time)} - ${escapeHtml(booking.end_time)}</strong>
          <span>${escapeHtml(booking.court_name)}</span>
        </div>
        <span class="source-badge ${booking.source}">${sourceLabel}</span>
      </div>

      <dl>
        <div>
          <dt>Name</dt>
          <dd>${escapeHtml(booking.name)}</dd>
        </div>
        <div>
          <dt>Kind</dt>
          <dd>${escapeHtml(booking.booking_kind)}</dd>
        </div>
        <div>
          <dt>Activity</dt>
          <dd>${escapeHtml(booking.activity_type || "N/A")}</dd>
        </div>
        <div>
          <dt>Booking type</dt>
          <dd>${escapeHtml(booking.booking_type || "N/A")}</dd>
        </div>
        <div>
          <dt>ID</dt>
          <dd>${escapeHtml(booking.booking_id)}</dd>
        </div>
      </dl>

      ${isMissing ? `<p class="missing-note">Exists in PadelMates but not in Playtomic.</p>` : ""}
    </article>
  `;
}

function compareBookings(a, b) {
  return `${a.start_time}${a.court_name}${a.source}`.localeCompare(
    `${b.start_time}${b.court_name}${b.source}`
  );
}

function groupBy(items, key) {
  return items.reduce((groups, item) => {
    const groupKey = item[key] || "Unknown";
    groups[groupKey] ||= [];
    groups[groupKey].push(item);
    return groups;
  }, {});
}

function formatShortDate(dateString) {
  const date = new Date(`${dateString}T00:00:00`);

  if (Number.isNaN(date.getTime())) {
    return dateString;
  }

  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export const incidentCategories = [
  "RETURN_REQUEST",
  "DAMAGE",
  "DELAYED_DELIVERY",
  "WRONG_ADDRESS",
  "LOST_PARCEL",
] as const;

export const incidentStatuses = ["open", "in_progress", "resolved", "discarded"] as const;
export const incidentOrigins = ["customer", "branch", "internal"] as const;
export const incidentBranches = ["Los Angeles", "Zaragoza", "central"] as const;

export type IncidentCategory = (typeof incidentCategories)[number];
export type IncidentStatus = (typeof incidentStatuses)[number];
export type IncidentOrigin = (typeof incidentOrigins)[number];
export type IncidentBranch = (typeof incidentBranches)[number];

export type Incident = {
  id: string;
  title: string;
  description: string;
  category: IncidentCategory;
  status: IncidentStatus;
  origin: IncidentOrigin;
  branch: IncidentBranch;
  created_at: string;
  updated_at: string;
};

export type IncidentSummary = {
  total: number;
  by_status: Record<IncidentStatus, number>;
  by_category: Record<IncidentCategory, number>;
  by_origin: Record<IncidentOrigin, number>;
  by_branch: Record<IncidentBranch, number>;
};

const apiBase = "/backend/api/incidents";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    throw new Error(response.status >= 500 ? "El servicio no está disponible ahora." : "Revisa los datos introducidos.");
  }
  return (await response.json()) as T;
}

export function listIncidents(filters: { status?: string; origin?: string; branch?: string }) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return request<Incident[]>(query ? `?${query}` : "");
}

export function getIncidentSummary() {
  return request<IncidentSummary>("/summary");
}

export function createIncident(payload: Omit<Incident, "id" | "created_at" | "updated_at">) {
  return request<Incident>("", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateIncidentStatus(id: string, status: IncidentStatus) {
  return request<Incident>(`/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

import { Candidate } from "../../types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://playground.4geeks.com/tracker/api/v1";

type CandidateFilters = {
  status?: string;
  stage?: string;
  search?: string;
};

type RawCandidate = {
  id: number | string;
  name?: string;
  full_name?: string;
  email?: string;
  phone?: string;
  position?: string;
  linkedin?: string;
  linkedin_url?: string;
  cv_url?: string;
  years_of_experience?: number;
  experience_years?: number;
  status?: string;
  stage?: string;
  applied_at?: string;
  created_at?: string;
};

type CandidatesResponse =
  | RawCandidate[]
  | {
      data?: RawCandidate[];
      results?: RawCandidate[];
      items?: RawCandidate[];
    };

function normalizeCandidate(item: RawCandidate): Candidate {
  return {
    id: item.id,
    name: item.name || item.full_name || "Sin nombre",
    email: item.email || "",
    phone: item.phone,
    position: item.position || "Sin puesto",
    linkedin: item.linkedin || item.linkedin_url,
    cv_url: item.cv_url,
    years_of_experience:
      item.years_of_experience ?? item.experience_years ?? undefined,
    status: item.status || "Sin estado",
    stage: item.stage || "Sin etapa",
    applied_at: item.applied_at,
    created_at: item.created_at,
  };
}

function extractCandidates(payload: CandidatesResponse): RawCandidate[] {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.results)) return payload.results;
  if (Array.isArray(payload?.items)) return payload.items;
  return [];
}

export async function getCandidates(
  filters?: CandidateFilters
): Promise<Candidate[]> {
  const url = new URL(`${API_BASE_URL}/records`);

  if (filters?.status) url.searchParams.append("status", filters.status);
  if (filters?.stage) url.searchParams.append("stage", filters.stage);
  if (filters?.search) url.searchParams.append("query", filters.search);

  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error("Error al obtener las candidaturas de TrackFlow");

  const payload = (await res.json()) as CandidatesResponse;
  const list = extractCandidates(payload);

  return list.map(normalizeCandidate);
}
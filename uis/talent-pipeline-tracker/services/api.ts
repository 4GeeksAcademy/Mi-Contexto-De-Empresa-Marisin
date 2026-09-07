import { Candidate, CandidateFormData, Note } from "@/types";

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

type RawNote = {
	id: number | string;
	record_id?: number | string;
	recordId?: number | string;
	content?: string;
	created_at?: string;
};

type ListPayload<T> =
	| T[]
	| {
			data?: T[];
			items?: T[];
			results?: T[];
			records?: T[];
		};

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function extractArray<T>(payload: unknown): T[] {
	if (Array.isArray(payload)) return payload as T[];
	if (!isObject(payload)) return [];

	const listPayload = payload as ListPayload<T>;

	if (Array.isArray(listPayload.data)) return listPayload.data;
	if (Array.isArray(listPayload.items)) return listPayload.items;
	if (Array.isArray(listPayload.results)) return listPayload.results;
	if (Array.isArray(listPayload.records)) return listPayload.records;

	return [];
}

function normalizeCandidate(raw: RawCandidate): Candidate {
	return {
		id: raw.id,
		name: raw.name || raw.full_name || "Sin nombre",
		email: raw.email || "",
		phone: raw.phone,
		position: raw.position || "Sin puesto",
		linkedin: raw.linkedin || raw.linkedin_url,
		cv_url: raw.cv_url,
		years_of_experience:
			raw.years_of_experience ?? raw.experience_years ?? undefined,
		status: raw.status || "Sin estado",
		stage: raw.stage || "Sin etapa",
		applied_at: raw.applied_at,
		created_at: raw.created_at,
	};
}

function normalizeNote(raw: RawNote): Note {
	return {
		id: raw.id,
		record_id: raw.record_id ?? raw.recordId ?? "",
		content: raw.content || "",
		created_at: raw.created_at,
	};
}

function toApiCandidatePayload(data: CandidateFormData) {
	return {
		name: data.name,
		full_name: data.name,
		email: data.email,
		phone: data.phone,
		position: data.position,
		linkedin: data.linkedin,
		linkedin_url: data.linkedin,
		cv_url: data.cv_url,
		years_of_experience: data.years_of_experience,
		experience_years: data.years_of_experience,
		status: data.status,
		stage: data.stage,
	};
}

async function readJson<T>(res: Response, errorMessage: string): Promise<T> {
	if (!res.ok) throw new Error(errorMessage);
	return (await res.json()) as T;
}

export async function getCandidates(filters?: CandidateFilters): Promise<Candidate[]> {
	const url = new URL(`${API_BASE_URL}/records`);

	if (filters?.status) url.searchParams.append("status", filters.status);
	if (filters?.stage) url.searchParams.append("stage", filters.stage);
	if (filters?.search) url.searchParams.append("query", filters.search);

	const res = await fetch(url.toString(), { cache: "no-store" });
	const payload = await readJson<unknown>(
		res,
		"Error al obtener las candidaturas de TrackFlow"
	);

	const rawCandidates = extractArray<RawCandidate>(payload);
	return rawCandidates.map(normalizeCandidate);
}

export async function getCandidateById(id: string | number): Promise<Candidate> {
	const res = await fetch(`${API_BASE_URL}/records/${id}`, { cache: "no-store" });
	const payload = await readJson<unknown>(res, "Candidatura no encontrada");

	if (isObject(payload) && isObject(payload.data)) {
		return normalizeCandidate(payload.data as RawCandidate);
	}

	return normalizeCandidate(payload as RawCandidate);
}

export async function createCandidate(data: CandidateFormData): Promise<Candidate> {
	const res = await fetch(`${API_BASE_URL}/records`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(toApiCandidatePayload(data)),
	});

	const payload = await readJson<unknown>(res, "Error al registrar la candidatura");
	if (isObject(payload) && isObject(payload.data)) {
		return normalizeCandidate(payload.data as RawCandidate);
	}

	return normalizeCandidate(payload as RawCandidate);
}

export async function updateCandidate(
	id: string | number,
	data: CandidateFormData
): Promise<Candidate> {
	const res = await fetch(`${API_BASE_URL}/records/${id}`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(toApiCandidatePayload(data)),
	});

	const payload = await readJson<unknown>(res, "Error al actualizar la candidatura");
	if (isObject(payload) && isObject(payload.data)) {
		return normalizeCandidate(payload.data as RawCandidate);
	}

	return normalizeCandidate(payload as RawCandidate);
}

export async function patchCandidate(
	id: string | number,
	fields: Partial<Pick<Candidate, "status" | "stage">>,
	currentCandidateData?: Candidate
): Promise<Candidate> {
	const payload: Partial<Pick<Candidate, "status" | "stage">> = {};

	if (typeof fields.status === "string") {
		payload.status = fields.status;
	}

	if (typeof fields.stage === "string") {
		payload.stage = fields.stage;
	}

	if (!payload.status && !payload.stage) {
		throw new Error("Debes enviar status o stage para actualizar la candidatura");
	}

	const patchRes = await fetch(`${API_BASE_URL}/records/${id}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});

	if (patchRes.ok) {
		if (patchRes.status === 204) {
			return getCandidateById(id);
		}

		const rawPayload = await patchRes.text();
		if (!rawPayload.trim()) {
			return getCandidateById(id);
		}

		const parsedPayload = JSON.parse(rawPayload) as unknown;
		if (isObject(parsedPayload) && isObject(parsedPayload.data)) {
			return normalizeCandidate(parsedPayload.data as RawCandidate);
		}

		if (isObject(parsedPayload)) {
			return normalizeCandidate(parsedPayload as RawCandidate);
		}

		return getCandidateById(id);
	}

	if (!currentCandidateData) {
		throw new Error("Error al cambiar el estado/etapa");
	}

	const mergedCandidate: Candidate = {
		...currentCandidateData,
		...payload,
	};

	const fallbackBody = toApiCandidatePayload({
		name: mergedCandidate.name,
		email: mergedCandidate.email,
		phone: mergedCandidate.phone,
		position: mergedCandidate.position,
		linkedin: mergedCandidate.linkedin,
		cv_url: mergedCandidate.cv_url,
		years_of_experience: mergedCandidate.years_of_experience,
		status: mergedCandidate.status,
		stage: mergedCandidate.stage,
	});

	const putRes = await fetch(`${API_BASE_URL}/records/${id}`, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(fallbackBody),
	});

	if (!putRes.ok) {
		throw new Error("Error al cambiar el estado/etapa");
	}

	if (putRes.status === 204) {
		return getCandidateById(id);
	}

	const putText = await putRes.text();
	if (!putText.trim()) {
		return getCandidateById(id);
	}

	const putPayload = JSON.parse(putText) as unknown;
	if (isObject(putPayload) && isObject(putPayload.data)) {
		return normalizeCandidate(putPayload.data as RawCandidate);
	}

	if (isObject(putPayload)) {
		return normalizeCandidate(putPayload as RawCandidate);
	}

	return getCandidateById(id);
}

export async function getNotes(recordId: string | number): Promise<Note[]> {
	const res = await fetch(`${API_BASE_URL}/records/${recordId}/notes`, {
		cache: "no-store",
	});
	const payload = await readJson<unknown>(res, "Error al cargar las notas");

	const rawNotes = extractArray<RawNote>(payload);
	return rawNotes.map((note) =>
		normalizeNote({ ...note, record_id: note.record_id ?? note.recordId ?? recordId })
	);
}

export async function addNote(
	recordId: string | number,
	content: string
): Promise<Note> {
	const res = await fetch(`${API_BASE_URL}/records/${recordId}/notes`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ content }),
	});

	const payload = await readJson<unknown>(res, "Error al anadir la nota interna");
	const rawNote = (isObject(payload) && isObject(payload.data)
		? payload.data
		: payload) as RawNote;

	return normalizeNote({
		...rawNote,
		record_id: rawNote.record_id ?? rawNote.recordId ?? recordId,
	});
}

export async function deleteNote(
	recordId: string | number,
	noteId: string | number
): Promise<void> {
	const res = await fetch(`${API_BASE_URL}/records/${recordId}/notes/${noteId}`, {
		method: "DELETE",
	});

	if (!res.ok) throw new Error("Error al eliminar la nota interna");
}
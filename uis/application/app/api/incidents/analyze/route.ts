import { NextResponse } from 'next/server';

// Reglas de negocio TrackFlow
const REQUIRED_FIELDS = [
  'incident_id', 'date', 'country', 'customer_type', 
  'tracking_number', 'carrier', 'category', 'description', 
  'status', 'customer_email'
];
const VALID_CATEGORIES = ['RETURN_REQUEST', 'DAMAGE', 'DELAYED_DELIVERY', 'WRONG_ADDRESS', 'LOST_PARCEL'];
const VALID_STATUSES = ['OPEN', 'CLOSED', 'DISCARDED'];

// Variable en memoria para almacenar temporalmente el último resultado exportable
let lastAnalysisResult: any[] = [];

export async function POST(request: Request) {
  try {
    const data = await request.formData();
    const file = data.get('file') as File;

    if (!file) {
      return NextResponse.json({ error: 'No se ha proporcionado ningún fichero.' }, { status: 400 });
    }

    const text = await file.text();
    const lines = text.split('\n').filter(line => line.trim() !== '');

    if (lines.length <= 1) {
      return NextResponse.json({ error: 'El fichero está vacío o solo contiene cabeceras.' }, { status: 400 });
    }

    const headers = lines[0].split(',').map(h => h.trim());
    
    // Validar cabeceras obligatorias
    for (const field of REQUIRED_FIELDS) {
      if (!headers.includes(field)) {
        return NextResponse.json({ error: `Falta la columna obligatoria: ${field}` }, { status: 400 });
      }
    }

    let validCount = 0;
    let invalidCount = 0;
    const invalidReasons = { missing_fields: 0, invalid_category: 0, invalid_status: 0 };
    const categoryTotals: Record<string, number> = {};
    const statusTotals: Record<string, number> = {};
    let satisfactionSum = 0;
    let satisfactionCount = 0;

    // Procesar filas
    for (let i = 1; i < lines.length; i++) {
      const values = lines[i].split(',').map(v => v.trim());
      const row: Record<string, string> = {};
      headers.forEach((h, index) => {
        row[h] = values[index] || '';
      });

      let isInvalid = false;

      // Comprobar campos vacíos
      for (const field of REQUIRED_FIELDS) {
        if (!row[field]) {
          isInvalid = true;
          invalidReasons.missing_fields++;
          break;
        }
      }

      if (isInvalid) {
        invalidCount++;
        continue;
      }

      // Comprobar categoría válida
      if (!VALID_CATEGORIES.includes(row['category'])) {
        invalidReasons.invalid_category++;
        invalidCount++;
        continue;
      }

      // Comprobar estado válido
      if (!VALID_STATUSES.includes(row['status'])) {
        invalidReasons.invalid_status++;
        invalidCount++;
        continue;
      }

      validCount++;

      // Acumular categorías
      categoryTotals[row['category']] = (categoryTotals[row['category']] || 0) + 1;

      // Acumular estados
      statusTotals[row['status']] = (statusTotals[row['status']] || 0) + 1;

      // Índice de satisfacción en CLOSED
      if (row['status'] === 'CLOSED' && row['satisfaction_score']) {
        const score = parseFloat(row['satisfaction_score']);
        if (!isNaN(score)) {
          satisfactionSum += score;
          satisfactionCount++;
        }
      }
    }

    const avgSatisfaction = satisfactionCount > 0 ? Number((satisfactionSum / satisfactionCount).toFixed(2)) : 0;

    const summary = {
      total_elements: lines.length - 1,
      valid_records: validCount,
      invalid_records: invalidCount,
      invalid_reasons: invalidReasons,
      category_breakdown: categoryTotals,
      status_breakdown: statusTotals,
      avg_satisfaction: avgSatisfaction
    };

    // Guardar para exportación CSV
    lastAnalysisResult = [
      { metric: 'total_elements', value: summary.total_elements },
      { metric: 'valid_records', value: summary.valid_records },
      { metric: 'invalid_records', value: summary.invalid_records },
      { metric: 'avg_satisfaction_closed', value: summary.avg_satisfaction },
      ...Object.entries(summary.category_breakdown).map(([k, v]) => ({ metric: `category_${k}`, value: v })),
      ...Object.entries(summary.status_breakdown).map(([k, v]) => ({ metric: `status_${k}`, value: v }))
    ];

    return NextResponse.json(summary, { status: 200 });

  } catch (error) {
    return NextResponse.json({ error: 'Error interno al procesar el fichero.' }, { status: 500 });
  }
}
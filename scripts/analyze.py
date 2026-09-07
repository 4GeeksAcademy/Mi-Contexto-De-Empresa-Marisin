"""
Script de Análisis de Incidencias para TrackFlow (Phase 1)
---------------------------------------------------------
Cumple con todos los requisitos del enunciado:
- Acepta la ruta del CSV por argumentos de línea de comandos.
- Detecta y contabiliza registros inválidos (campos faltantes o valores no permitidos).
- Calcula métricas clave sobre registros válidos:
  * Total de elementos procesados (válidos e inválidos).
  * Totalización por categoría de incidencia.
  * Totalización por estado (OPEN, CLOSED, DISCARDED).
  * Índice de satisfacción medio en casos CLOSED con puntuación.
- Pregunta de forma interactiva si se desea exportar a 'results.csv'.
"""

import sys
import os
import pandas as pd

# Definición de reglas de negocio para TrackFlow
REQUIRED_FIELDS = [
    'incident_id', 'date', 'country', 'customer_type', 
    'tracking_number', 'carrier', 'category', 'description', 
    'status', 'customer_email'
]
VALID_CATEGORIES = ['RETURN_REQUEST', 'DAMAGE', 'DELAYED_DELIVERY', 'WRONG_ADDRESS', 'LOST_PARCEL']
VALID_STATUSES = ['OPEN', 'CLOSED', 'DISCARDED']

def main():
    # 1. Comprobar que se pasa la ruta del fichero como argumento
    if len(sys.argv) < 2:
        print("Uso correcto: python analyze.py <ruta_al_fichero.csv>")
        sys.exit(1)

    csv_path = sys.argv[1]

    if not os.path.exists(csv_path):
        print(f"[Error] El archivo '{csv_path}' no existe.")
        sys.exit(1)

    # 2. Cargar el fichero CSV
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"[Error] No se pudo leer el archivo CSV: {e}")
        sys.exit(1)

    total_rows = len(df)
    valid_records = []
    invalid_count = 0
    invalid_reasons = {
        "missing_fields": 0,
        "invalid_category": 0,
        "invalid_status": 0
    }

    # 3. Validar fila por fila
    for idx, row in df.iterrows():
        is_invalid = False
        
        # Verificar campos obligatorios vacíos o nulos
        for field in REQUIRED_FIELDS:
            if field not in df.columns or pd.isna(row[field]) or str(row[field]).strip() == '':
                is_invalid = True
                invalid_reasons["missing_fields"] += 1
                break
        
        if is_invalid:
            invalid_count += 1
            continue

        # Verificar categoría válida
        cat = row['category']
        if cat not in VALID_CATEGORIES:
            is_invalid = True
            invalid_reasons["invalid_category"] += 1
            invalid_count += 1
            continue

        # Verificar estado válido
        st = row['status']
        if st not in VALID_STATUSES:
            is_invalid = True
            invalid_reasons["invalid_status"] += 1
            invalid_count += 1
            continue

        if not is_invalid:
            valid_records.append(row)

    df_valid = pd.DataFrame(valid_records)
    valid_count = len(df_valid)

    # 4. Calcular métricas sobre registros válidos
    category_totals = df_valid['category'].value_counts().to_dict() if valid_count > 0 else {}
    status_totals = df_valid['status'].value_counts().to_dict() if valid_count > 0 else {}

    # Índice de satisfacción medio en casos CLOSED con puntuación registrada
    avg_satisfaction = 0.0
    if valid_count > 0 and 'satisfaction_score' in df_valid.columns:
        closed_df = df_valid[df_valid['status'] == 'CLOSED']
        scored_closed = closed_df.dropna(subset=['satisfaction_score'])
        if len(scored_closed) > 0:
            avg_satisfaction = float(scored_closed['satisfaction_score'].mean())

    # 5. Imprimir resumen por consola con formato legible
    print("\n" + "="*50)
    print("       INFORME DE ANÁLISIS DE INCIDENCIAS - TRACKFLOW")
    print("="*50)
    print(f"📁 Archivo analizado: {csv_path}")
    print(f"🔹 Total de elementos en el fichero: {total_rows}")
    print(f"✅ Registros válidos procesados: {valid_count}")
    print(f"❌ Registros inválidos descartados: {invalid_count}")
    if invalid_count > 0:
        print(f"   - Por campos faltantes o vacíos: {invalid_reasons['missing_fields']}")
        print(f"   - Por categoría no válida: {invalid_reasons['invalid_category']}")
        print(f"   - Por estado no válido: {invalid_reasons['invalid_status']}")
    
    print("\n--- TOTALIZACIÓN POR CATEGORÍA ---")
    for cat, count in category_totals.items():
        print(f"   • {cat}: {count}")

    print("\n--- TOTALIZACIÓN POR ESTADO ---")
    for st, count in status_totals.items():
        print(f"   • {st}: {count}")

    print("\n--- MÉTRICAS DE CALIDAD ---")
    print(f"   • Índice de satisfacción medio (Casos Cerrados): {avg_satisfaction:.2f} / 5.0")
    print("="*50 + "\n")

    # 6. Preguntar al usuario si desea exportar a CSV
    export_choice = input("¿Deseas exportar los resultados a CSV? [s / n]: ").strip().lower()
    
    if export_choice == 's':
        results_data = [
            {"metric": "total_elements", "value": total_rows},
            {"metric": "valid_records", "value": valid_count},
            {"metric": "invalid_records", "value": invalid_count},
            {"metric": "avg_satisfaction_closed", "value": round(avg_satisfaction, 2)}
        ]
        # Añadir desgloses por categoría y estado al reporte
        for cat, count in category_totals.items():
            results_data.append({"metric": f"category_{cat}", "value": count})
        for st, count in status_totals.items():
            results_data.append({"metric": f"status_{st}", "value": count})

        df_results = pd.DataFrame(results_data)
        output_filename = "results.csv"
        df_results.to_csv(output_filename, index=False)
        print(f"[Éxito] Resultados exportados correctamente a '{output_filename}'.")
    else:
        print("Exportación omitida por el usuario.")

if __name__ == "__main__":
    main()
    
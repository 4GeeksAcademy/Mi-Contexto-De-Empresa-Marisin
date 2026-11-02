from .database import products_table, seed_database, suppliers_table


def run_seed():
  seed_database()
  print(
      f"Seed completado: {len(suppliers_table.all())} proveedores, "
      f"{len(products_table.all())} productos. Datos existentes conservados."
  )


if __name__ == "__main__":
  run_seed()
  
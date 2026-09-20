FROM apache/fineract:1.9.0

# Fineract database driver gara PostgreSQL (Neon) jijjiiruuf
ENV FINERACT_HIKARI_DRIVER_CLASS_NAME=org.postgresql.Driver

# Teessoo JDBC database (Render irratti Environment Variable irraa dubbisa)
ENV FINERACT_HIKARI_JDBC_URL=${FINERACT_JDBC_URL}
ENV FINERACT_HIKARI_USERNAME=${NEON_USERNAME}
ENV FINERACT_HIKARI_PASSWORD=${NEON_PASSWORD}

EXPOSE 8080

# Database credential key rotation

The Fernet key encrypts provider keys, webhook settings, and MCP auth/OAuth
credentials and headers. The key is not stored in the database. Rotate it during
a maintenance window with every control-plane process stopped; the database
transaction will rewrite all protected fields atomically.

1. Record the current key in the approved secret manager and generate a
   replacement Fernet key. Do not put either key in source control or command
   history.
2. Create a protected database backup using the current key. For SQLite, use
   `python -m ai_bridge.control.backup SOURCE.db NEW_BACKUP.db`. For PostgreSQL,
   use the provider's encrypted snapshot/PITR or a protected `pg_dump`.
3. Stop every control-plane process and verify none can write to the database.
4. Supply the existing key as `AI_BRIDGE_DB_ENCRYPTION_KEY` and the replacement
   as `AI_BRIDGE_DB_ENCRYPTION_KEY_NEW` through the secret manager or process
   environment. Run:

   ```sh
   python -m ai_bridge.control.rotate_secrets
   ```

5. Only after the command reports success, replace
   `AI_BRIDGE_DB_ENCRYPTION_KEY` in the service secret manager with the new key,
   remove `AI_BRIDGE_DB_ENCRYPTION_KEY_NEW`, and restart the control plane.
6. Verify provider/connector configured status and run a non-destructive
   connection check. Keep the old key protected until a restore drill proves
   the rotated database backup can be restored with the replacement key.

If the command fails, it does not print credential values and the rotation
transaction rolls back. Keep the old key configured; investigate the database
and key outside the service. The startup legacy-secret migration may encrypt
previously plaintext fields with the old key before rotation begins, so a failed
rotation still requires the old key. Never restore a pre-rotation backup using
the new key: that backup requires the old key.

The command validates every existing encrypted token with the old key before
committing the new ciphertext. It does not rotate credentials stored outside
the database, such as environment variables or external service accounts.

package it.unisalento.iotedgecompanion;

/** Errore HTTP controllato usato dal client backend. */
final class ApiException extends Exception {
    private final int statusCode;

    ApiException(int statusCode, String message) {
        super(message);
        this.statusCode = statusCode;
    }

    int statusCode() {
        return statusCode;
    }
}

def make_response(status_code=200, message=None):
    return {
        "statusCode": status_code,
        "body": {
            "message": f"{message}"
        }
    }
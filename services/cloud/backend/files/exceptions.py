class FileAdmissionError(Exception):
    pass


class FileAdmissionDisabled(FileAdmissionError):
    pass


class FileValidation(FileAdmissionError):
    pass


class FileConflict(FileAdmissionError):
    pass


class FileTooLarge(FileAdmissionError):
    pass


class FileUnavailable(FileAdmissionError):
    pass


class FileScopeUnavailable(FileAdmissionError):
    pass

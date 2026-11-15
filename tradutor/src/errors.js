// Erro com código estável e status HTTP; a mensagem já é própria para o usuário final.
export class TranslationError extends Error {
  constructor(code, message, status = 500) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

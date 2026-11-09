package com.baixador.salvar;

import androidx.core.content.FileProvider;

/** Entrega o APK baixado ao instalador do Android. Classe própria para não colidir com o FileProvider do Capacitor no manifesto. */
public class ApkFileProvider extends FileProvider {}

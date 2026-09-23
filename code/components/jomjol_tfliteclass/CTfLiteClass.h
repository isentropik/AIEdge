#pragma once

#ifndef CTFLITECLASS_H
#define CTFLITECLASS_H

#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "esp_err.h"
#include "esp_log.h"

#include "CImageBasis.h"


class CTfLiteClass
{
    protected:
        tflite::MicroMutableOpResolver<10> resolver;  
        const tflite::Model* model;
        tflite::MicroInterpreter* interpreter;
        TfLiteTensor* output = nullptr;     

        int kTensorArenaSize;
        uint8_t *tensor_arena;

        unsigned char *modelfile = NULL;
        size_t loadedModelBytes = 0;
        bool verifiedPolarModel = false;


        float* input;
        int input_i;
        int im_height, im_width, im_channel;

        long GetFileSize(std::string filename);
        bool ReadFileToModel(std::string _fn);
        void MakeStaticResolver();

    public:
        CTfLiteClass();
        ~CTfLiteClass();        
        bool LoadModel(std::string _fn);
        bool LoadFrozenPolarModel(std::string filename);
        // Workspace shares the reserved model region and expires with this object.
        void* GetPolarWorkspace(size_t bytes);
        bool MakeAllocate();
        void GetInputTensorSize();
        bool LoadInputImageBasis(CImageBasis *rs);
        // Dedicated polar path; caller supplies frozen-preprocessing int8 features.
        // False means no reading; result remains unchanged on failure.
        bool HasPolarTensorContract();
        bool InferPolar(const int8_t* features, size_t count, bool ccw, float& result);
        bool InvokePolar(const int8_t* features, size_t count);
        bool InferPolarScores(const int8_t* features, size_t count, int8_t* scores, size_t scoreCount);
        void Invoke();
        int GetAnzOutPut(bool silent = true);        
        int GetOutClassification(int _von = -1, int _bis = -1);

        int GetClassFromImageBasis(CImageBasis *rs);
        std::string GetStatusFlow();

        float GetOutputValue(int nr);
        void GetInputDimension(bool silent);
        int ReadInputDimenstion(int _dim);
};

#endif //CTFLITECLASS_H
